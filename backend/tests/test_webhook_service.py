from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app.integrations as integrations_pkg
import app.webhook as webhook_pkg
from app.api.security import RepoPathError
from app.api.settings import WebSettings
from app.core.rules.common.models import (
    ChangeStatus,
    DegradedModule,
    FileGroup,
    Finding,
    IssueLevel,
    ReportStatus,
    build_report,
)
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import OpenApiMode
from app.webhook.app import create_webhook_app
from app.webhook.models import (
    ChangedFilesSource,
    EventKind,
    NormalizedEvent,
    ReviewJob,
    utc_now,
)
from app.webhook.queue import ReviewQueue
from app.webhook.security import RepoMappingError, resolve_event_repo
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import FrozenClock, WebhookASGIClient, make_headers, make_payload, no_network

WEBHOOK_DIR = Path(webhook_pkg.__file__).resolve().parent
INTEGRATIONS_DIR = Path(integrations_pkg.__file__).resolve().parent
FORBIDDEN_MODULES = ("naming", "code_scan", "link_check", "sensitive")


def _product_files() -> list[Path]:
    return sorted([*WEBHOOK_DIR.glob("*.py"), *INTEGRATIONS_DIR.glob("*.py")])


def _root(temp: str) -> Path:
    path = Path(temp) / "lab-01"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings(root: Path) -> WebSettings:
    return WebSettings(allowed_repo_roots=(root.resolve(),), default_repo=root.name, static_dir=root)


def _payload(*, event_id: str, **kwargs: object) -> dict[str, object]:
    payload = make_payload(**kwargs)
    payload["event_id"] = event_id
    return payload


def _clean_report():
    return build_report(status=ReportStatus.OK, files=(FileGroup("main.py", ChangeStatus.MODIFY),))


def _event(event_id: str = "evt-job") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        event_kind=EventKind.CREATED,
        repository_identifier="acme/lab-01",
        repo_label="lab-01",
        pull_request_number=12,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=("main.py",),
        changed_files_source=ChangedFilesSource.PAYLOAD,
        changed_files_available=True,
        illegal_paths=(),
        signature_verified=True,
        occurred_at=utc_now(),
    )


def _job(root: Path, event_id: str = "evt-job") -> ReviewJob:
    return ReviewJob(
        event=_event(event_id),
        repo_root=root.resolve(),
        manifest_text="M main.py\n",
        entry_count=1,
        created_at=utc_now(),
        attempt=1,
        request_id="req-1",
    )


class _CountingRunner:
    def __init__(self, report=None, error: Exception | None = None) -> None:
        self.calls: list[tuple[object, object, object]] = []
        self._report = report
        self._error = error

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls.append((manifest_text, repo_root, config))
        if self._error is not None:
            raise self._error
        return self._report if self._report is not None else _clean_report()


class _BlockingRunner:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls = 0

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls += 1
        self.started.set()
        self.release.wait(10)
        return _clean_report()


class ServiceTest(unittest.TestCase):
    def test_repo_mapping_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            settings = _settings(root)
            config = WebhookConfig()
            self.assertEqual(resolve_event_repo("acme/lab-01", settings, config).resolve(), root.resolve())
            self.assertEqual(resolve_event_repo("lab-01", settings, config).resolve(), root.resolve())
            mapped = WebhookConfig(repo_map={"acme/whatever": "lab-01"})
            self.assertEqual(resolve_event_repo("acme/whatever", settings, mapped).resolve(), root.resolve())

    def test_repo_forbidden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            settings = _settings(root)
            config = WebhookConfig()
            calls: list[str] = []

            def fake_resolve(token: str, web_settings: WebSettings) -> Path:
                calls.append(token)
                raise RepoPathError("REPO_FORBIDDEN", 403, "不允许访问仓库白名单之外的路径")

            with patch("app.webhook.security.resolve_repo_root", side_effect=fake_resolve):
                with self.assertRaises(RepoMappingError) as context:
                    resolve_event_repo("evil/repo", settings, config)
            self.assertEqual(context.exception.code, "WEBHOOK_REPO_FORBIDDEN")
            self.assertEqual(context.exception.status_code, 403)
            self.assertEqual(context.exception.message, "仓库不在服务端允许范围内")
            self.assertEqual(calls, ["evil/repo", "repo"])

    def test_no_remote_clone(self):
        files = _product_files()
        self.assertEqual(len(files), 18)
        hits: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "subprocess" in text or "os.system" in text or "clone(" in text:
                hits.append(path.name)
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in {"subprocess"}:
                            hits.append(f"{path.name}:import")
                elif isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id == "clone":
                        hits.append(f"{path.name}:clone")
                    if isinstance(func, ast.Attribute) and func.attr == "system":
                        owner = getattr(func.value, "id", "")
                        if owner == "os":
                            hits.append(f"{path.name}:os.system")
        self.assertEqual(hits, [])

    def test_run_check_called_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            config = WebhookConfig(secret="fake", openapi_mode=OpenApiMode.MOCK, queue_capacity=1, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner, adapter=MockOpenApiAdapter())
            job = _job(root)
            record = service.process_job(job)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0][0], "M main.py\n")
            self.assertIsNone(runner.calls[0][2])
            self.assertEqual(record.check_status, "正常")
            self.assertEqual(record.delivery_status, "mock_delivered")
            self.assertIsNone(record.error_code)

    def test_no_module_imports(self):
        files = _product_files()
        self.assertEqual(len(files), 18)
        hits: list[str] = []
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = (node.module or "").replace("\\", ".")
                    leaf = module.rsplit(".", 1)[-1]
                    if leaf in FORBIDDEN_MODULES:
                        hits.append(f"{path.name}:{module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        leaf = alias.name.rsplit(".", 1)[-1]
                        if leaf in FORBIDDEN_MODULES:
                            hits.append(f"{path.name}:{alias.name}")
        self.assertEqual(hits, [])

    def test_engine_degraded_passthrough(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            report = build_report(
                status=ReportStatus.PARTIAL_DEGRADED,
                files=(
                    FileGroup(
                        "main.py",
                        ChangeStatus.MODIFY,
                        findings=(
                            Finding(
                                IssueLevel.MUST_FIX,
                                "main.py",
                                "命名不符合规范要求",
                                "请重命名文件",
                                "naming-001",
                                1,
                            ),
                        ),
                    ),
                ),
                degraded_modules=(DegradedModule("命名与目录检查", "模块初始化失败"),),
            )
            config = WebhookConfig(secret="fake", openapi_mode=OpenApiMode.MOCK)
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=_CountingRunner(report=report), adapter=adapter)
            record = service.process_job(_job(root))
            self.assertEqual(record.check_status, "部分降级")

            self.assertEqual(len(adapter.comments), 1)
            payload = adapter.comments[0]
            self.assertEqual(payload.degraded_module_count, 1)
            self.assertIn("降级模块：1 个", payload.markdown)
            self.assertIn("模块初始化失败", payload.markdown)

    def test_engine_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            config = WebhookConfig(secret="fake", openapi_mode=OpenApiMode.MOCK)
            adapter = MockOpenApiAdapter()
            runner = _CountingRunner(error=RuntimeError("boom"))
            service = WebhookService(config, _settings(root), runner=runner, adapter=adapter)
            record = service.process_job(_job(root))
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(record.check_status, "失败")
            self.assertEqual(record.delivery_status, "failed")
            self.assertEqual(record.error_code, "WEBHOOK_ENGINE_ERROR")
            self.assertEqual(record.reason, "规则引擎执行异常，检查未完成")
            self.assertEqual(len(adapter.comments), 1)
            markdown = adapter.comments[0].markdown
            self.assertNotIn("未发现问题", markdown)
            self.assertIn("本次未执行检查", markdown)

    def test_engine_input_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            report = build_report(
                status=ReportStatus.INPUT_ERROR,
                files=(),
                warnings=("输入存在错误，本次检查未完整执行",),
            )
            config = WebhookConfig(secret="fake", openapi_mode=OpenApiMode.MOCK)
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=_CountingRunner(report=report), adapter=adapter)
            record = service.process_job(_job(root))
            self.assertEqual(record.check_status, "输入错误")
            self.assertEqual(len(adapter.comments), 1)
            self.assertIn("检查状态：输入错误", adapter.comments[0].markdown)

    def test_task_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            clock = FrozenClock(1_000.0)
            config = WebhookConfig(secret="fake", task_timeout_seconds=30.0, queue_capacity=1, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner, clock=clock)
            record = service._queue.run_now(_job(root), timeout=0.0)
            try:
                self.assertEqual(runner.calls, [])
                self.assertEqual(record.check_status, "超时")
                self.assertEqual(record.error_code, "WEBHOOK_TIMEOUT")
                self.assertEqual(record.delivery_status, "not_attempted")
                self.assertEqual(record.reason, "检查队列等待超时")
            finally:
                service.shutdown(2.0)

    def test_queue_full(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, queue_capacity=1, worker_concurrency=1)
            started = threading.Event()
            release = threading.Event()
            runner = _BlockingRunner(started, release)
            service = WebhookService(config, _settings(root), runner=runner, adapter=MockOpenApiAdapter())
            app = create_webhook_app(config, service=service)
            client = WebhookASGIClient(app)
            raw_a = json.dumps(_payload(repo=root.name, event_id="evt-w38-a", changed_files=["main.py"]), ensure_ascii=False).encode("utf-8")
            raw_b = json.dumps(_payload(repo=root.name, event_id="evt-w38-b", changed_files=["main.py"]), ensure_ascii=False).encode("utf-8")
            raw_c = json.dumps(_payload(repo=root.name, event_id="evt-w38-c", changed_files=["main.py"]), ensure_ascii=False).encode("utf-8")
            try:
                first = client.post(config.path, content=raw_a, headers=_headers(secret, raw_a))
                self.assertEqual(first.status_code, 202)
                self.assertTrue(started.wait(10))
                second = client.post(config.path, content=raw_b, headers=_headers(secret, raw_b))
                self.assertEqual(second.status_code, 202)
                third = client.post(config.path, content=raw_c, headers=_headers(secret, raw_c))
                self.assertEqual(third.status_code, 429)
                self.assertEqual(third.json()["error"]["code"], "WEBHOOK_BUSY")
                reservation = service._registry.reserve("evt-w38-c", hashlib.sha256(raw_c).hexdigest())
                self.assertEqual(reservation.state.name, "NEW")
            finally:
                release.set()
                service.shutdown(5.0)


def _headers(secret: str, raw: bytes) -> dict[str, str]:
    headers = make_headers(secret, raw)
    headers["Content-Type"] = "application/json"
    return headers


if __name__ == "__main__":
    unittest.main()
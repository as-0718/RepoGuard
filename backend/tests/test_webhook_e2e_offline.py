from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.api.settings import WebSettings
from app.core.rules.engine import run_check
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import OpenApiMode
from app.webhook.app import create_webhook_app
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import WebhookASGIClient, make_headers, make_payload, no_network


def _root(temp: str) -> Path:
    path = Path(temp) / "lab-e2e"
    path.mkdir(parents=True, exist_ok=True)
    (path / "notes").mkdir(parents=True, exist_ok=True)
    (path / "notes" / "ok.txt").write_text("hello\n", encoding="utf-8")
    (path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (path / "util.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    return path


def _settings(root: Path) -> WebSettings:
    return WebSettings(allowed_repo_roots=(root.resolve(),), default_repo=root.name, static_dir=root)


def _payload(*, event_id: str, **kwargs: object) -> dict[str, object]:
    payload = make_payload(**kwargs)
    payload["event_id"] = event_id
    return payload


def _headers(secret: str, raw: bytes) -> dict[str, str]:
    headers = make_headers(secret, raw)
    headers["Content-Type"] = "application/json"
    return headers


class _RealRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.configs: list[object] = []
        self.report = None

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls += 1
        self.configs.append(config)
        self.report = run_check(manifest_text, repo_root, config)
        return self.report


class _SignalingService(WebhookService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.remembered = threading.Event()

    def _remember(self, record) -> None:
        super()._remember(record)
        self.remembered.set()


class OfflineE2ETest(unittest.TestCase):
    def test_offline_e2e(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(
                secret=secret,
                openapi_mode=OpenApiMode.MOCK,
                queue_capacity=2,
                worker_concurrency=1,
            )
            adapter = MockOpenApiAdapter()
            runner = _RealRunner()
            service = _SignalingService(config, _settings(root), runner=runner, adapter=adapter)
            app = create_webhook_app(config, service=service)
            payload = _payload(
                repo=root.name,
                event_id="evt-e2e-001",
                pr_number=12,
                changed_files=["notes/ok.txt"],
            )
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            try:
                response = WebhookASGIClient(app).post(config.path, content=raw, headers=_headers(secret, raw))
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["status"], "accepted")
                self.assertTrue(service.remembered.wait(10))
                service.shutdown(5.0)

                self.assertEqual(runner.calls, 1)
                self.assertEqual(runner.configs, [None])
                report = runner.report
                self.assertIsNotNone(report)
                self.assertEqual(report.status.value, "正常")
                self.assertEqual(report.summary.issue_count, 0)

                self.assertEqual(len(adapter.comments), 1)
                payload_out = adapter.comments[0]
                marker = "<!-- repoguard:event:evt-e2e-001 -->"
                self.assertEqual(payload_out.marker, marker)
                self.assertTrue(payload_out.markdown.endswith(marker))
                self.assertIn("本次检查未发现问题", payload_out.markdown)
                self.assertIn(
                    f"问题统计：共 {report.summary.issue_count} 个"
                    f"（必须修改 {report.summary.must_fix_count}，优化建议 {report.summary.suggestion_count}）",
                    payload_out.markdown,
                )
                self.assertIn("变更文件：1 个（来源：payload）", payload_out.markdown)
                self.assertEqual(payload_out.char_count, len(payload_out.markdown))
                self.assertEqual(payload_out.must_fix_count, report.summary.must_fix_count)
                self.assertEqual(payload_out.suggestion_count, report.summary.suggestion_count)
                self.assertEqual(payload_out.issue_count, report.summary.issue_count)

                record = service.recent_records(1)[0]
                self.assertEqual(record.delivery_status, "mock_delivered")
                self.assertEqual(record.check_status, "正常")
                self.assertEqual(record.changed_file_count, 1)
                self.assertEqual(record.comment_chars, len(payload_out.markdown))
                self.assertEqual(record.event_id, "evt-e2e-001")
                self.assertIsNone(record.error_code)
            finally:
                service.shutdown(5.0)

    @unittest.skipUnless(
        os.environ.get("REPOGUARD_WEBHOOK_E2E_LOOPBACK") == "1",
        "回环 E2E 需显式开启 REPOGUARD_WEBHOOK_E2E_LOOPBACK=1",
    )
    def test_loopback_e2e_optional(self):
        import httpx
        import uvicorn

        with tempfile.TemporaryDirectory() as temp:
            root = _root(temp)
            config = WebhookConfig(secret=os.urandom(16).hex(), queue_capacity=2, worker_concurrency=1)

            def runner(manifest_text, repo_root, config=None):
                return run_check(manifest_text, repo_root, config)

            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
            )
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5.0
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(server.started, "回环服务未在 5 秒内启动")
                port = server.servers[0].sockets[0].getsockname()[1]
                response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=5.0)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["service"], "repoguard-webhook")
                self.assertEqual(response.json()["openapi_mode"], "disabled")
            finally:
                server.should_exit = True
                thread.join(5.0)
                service.shutdown(2.0)


if __name__ == "__main__":
    unittest.main()
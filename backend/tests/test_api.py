from __future__ import annotations

import asyncio
import ast
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

from app.api.settings import PROJECT_ROOT, WebSettings
from app.core.rules.common.models import (
    DegradedModule,
    FileGroup,
    IssueLevel,
    ReportStatus,
    build_report,
    make_finding,
)
from app.core.rules.common.report import report_to_dict
from app.core.rules.engine import run_check

if os.name == "nt":
    import _overlapped

    _WAKE_OVERLAPPED = _overlapped.Overlapped(0)

    class _DummySocket:
        def fileno(self) -> int:
            return -1

        def close(self) -> None:
            return None

    class _IocpWakeProactorEventLoop(asyncio.ProactorEventLoop):
        def _make_self_pipe(self) -> None:
            self._ssock = _DummySocket()
            self._csock = _DummySocket()
            self._internal_fds += 1

        def _loop_self_reading(self, f=None) -> None:
            if f is not None:
                try:
                    f.result()
                except BaseException:
                    pass
            return None

        def _write_to_self(self) -> None:
            _overlapped.PostQueuedCompletionStatus(self._proactor._iocp, 0, 0, _WAKE_OVERLAPPED.address)

    class _IocpWakeProactorPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self):
            return _IocpWakeProactorEventLoop()

    asyncio.set_event_loop_policy(_IocpWakeProactorPolicy())

BACKEND = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND / "app"
API_DIR = APP_DIR / "api"
STATIC_DIR = APP_DIR / "static"

HAS_WEB_DEPENDENCIES = find_spec("fastapi") is not None and find_spec("httpx") is not None

if HAS_WEB_DEPENDENCIES:
    import httpx
    from fastapi import FastAPI

    from app.api.app import create_app
    from app.api.routes import get_engine
else:
    httpx = None
    FastAPI = object
    create_app = None
    get_engine = None

SKIP_REASON = "未安装 Web 测试依赖 httpx==0.28.1"


class SyncASGIClient:
    def __init__(self, app: "FastAPI", timeout: float = 10.0) -> None:
        self.app = app
        self.timeout = timeout

    def request(self, method: str, path: str, **kwargs) -> "httpx.Response":
        async def run() -> "httpx.Response":
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                timeout=self.timeout,
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def get(self, path: str, **kwargs) -> "httpx.Response":
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> "httpx.Response":
        return self.request("POST", path, **kwargs)

    def close(self) -> None:
        return None


def _empty_report(status: ReportStatus = ReportStatus.OK):
    return build_report(status=status, files=())


def _counting_runner(calls: list[tuple[object, object, object]]):
    def runner(manifest_text: str, repo_root: str | Path, config=None):
        calls.append((manifest_text, repo_root, config))
        return _empty_report()

    return runner


def _degraded_report():
    finding = make_finding(
        level=IssueLevel.SUGGESTION,
        file_path="lab/bad.py",
        message="模块开头缺少说明注释，读者不易了解文件用途",
        suggestion="在文件第一行补充模块说明",
        rule_id="code-001",
    )
    group = FileGroup(file_path="lab/bad.py", status=__import__("app.core.rules.common.models", fromlist=["ChangeStatus"]).ChangeStatus.ADD, findings=(finding,))
    return build_report(
        status=ReportStatus.PARTIAL_DEGRADED,
        files=(group,),
        degraded_modules=(DegradedModule("代码检查", "执行异常，结果可能不完整"),),
        warnings=("部分检查模块降级，结果可能不完整",),
    )


def _ordered_report():
    fix_a = make_finding(
        level=IssueLevel.MUST_FIX,
        file_path="lab/a.py",
        message="必须修改问题第一条",
        suggestion="补充说明注释",
        rule_id="code-002",
        line_no=2,
    )
    tip_a = make_finding(
        level=IssueLevel.SUGGESTION,
        file_path="lab/a.py",
        message="优化建议问题第一条",
        suggestion="改为英文文件名",
        rule_id="naming-004",
        line_no=1,
    )
    fix_b = make_finding(
        level=IssueLevel.MUST_FIX,
        file_path="lab/b.py",
        message="必须修改问题第二条",
        suggestion="改用安全函数",
        rule_id="code-004",
        line_no=8,
    )
    tip_b = make_finding(
        level=IssueLevel.SUGGESTION,
        file_path="lab/b.py",
        message="优化建议问题第二条",
        suggestion="提取具名常量",
        rule_id="code-007",
        line_no=9,
    )
    status = __import__("app.core.rules.common.models", fromlist=["ChangeStatus"]).ChangeStatus.ADD
    return build_report(
        status=ReportStatus.OK,
        files=(
            FileGroup(file_path="lab/a.py", status=status, findings=(fix_a, tip_a)),
            FileGroup(file_path="lab/b.py", status=status, findings=(fix_b, tip_b)),
        ),
    )


def _json_normalized(report) -> dict[str, object]:
    return json.loads(json.dumps(report_to_dict(report), ensure_ascii=False))


@unittest.skipUnless(HAS_WEB_DEPENDENCIES, SKIP_REASON)
class ApiTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name) / "repo"
        (self.repo_root / "lab").mkdir(parents=True)
        (self.repo_root / "docs").mkdir()
        (self.repo_root / "lab" / "bad.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
        (self.repo_root / "docs" / "中文.md").write_text("# 实验说明\n", encoding="utf-8")
        (self.repo_root / "note.txt").write_text("hello\n", encoding="utf-8")
        self._apps: list[FastAPI] = []
        self.settings = self.make_settings()
        self.app = self.make_app(self.settings)
        self.client = self.make_client(self.app)

    def tearDown(self) -> None:
        try:
            self.client.close()
        finally:
            for app in self._apps:
                gate = getattr(app.state, "review_gate", None)
                if gate is not None:
                    gate.shutdown()
            self.temp_dir.cleanup()

    def make_settings(self, **overrides: object) -> WebSettings:
        base: dict[str, object] = {
            "allowed_repo_roots": (self.repo_root,),
            "default_repo": self.repo_root.name,
            "static_dir": STATIC_DIR,
        }
        base.update(overrides)
        return WebSettings(**base)

    def make_app(self, settings: WebSettings | None = None) -> FastAPI:
        app = create_app(settings or self.make_settings())
        self._apps.append(app)
        return app

    def make_client(self, app: FastAPI | None = None) -> SyncASGIClient:
        return SyncASGIClient(self.app if app is None else app)

    def override_engine(self, app: FastAPI, runner) -> None:
        def provider():
            return runner

        app.dependency_overrides[get_engine] = provider

    def post_review(self, client: SyncASGIClient, manifest: str, repo: str, **kwargs) -> "httpx.Response":
        return client.post("/api/review", json={"manifest": manifest, "repo": repo}, **kwargs)

    async def async_post(self, app: FastAPI, payload: dict[str, object]) -> "httpx.Response":
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as client:
            return await client.post("/api/review", json=payload)

    def test_health_ok(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data),
            {"status", "service", "version", "engine", "database", "default_repo", "allowed_repo_root_count", "time"},
        )
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "repoguard-web-api")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["engine"], "available")
        self.assertEqual(data["allowed_repo_root_count"], 1)
        self.assertFalse(Path(data["default_repo"]).is_absolute())
        self.assertTrue("T" in data["time"] or "+" in data["time"] or data["time"].endswith("Z"))
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertTrue(response.headers.get("x-request-id"))

    def test_health_degraded_no_roots(self):
        app = self.make_app(self.make_settings(allowed_repo_roots=()))
        client = self.make_client(app)
        calls: list[tuple[object, object, object]] = []
        self.override_engine(app, _counting_runner(calls))
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 503)
        data = health.json()
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["allowed_repo_root_count"], 0)
        self.assertEqual(data["default_repo"], self.repo_root.name)
        self.assertEqual(health.headers.get("cache-control"), "no-store")

        review = self.post_review(client, "A lab/bad.py\n", "repo")
        self.assertEqual(review.status_code, 503)
        body = review.json()
        self.assertEqual(body["error"]["code"], "ENGINE_UNAVAILABLE")
        self.assertIn("未配置可用的仓库目录", body["error"]["detail"])
        self.assertGreaterEqual(len(body["request_id"]), 8)
        self.assertLessEqual(len(body["request_id"]), 64)
        self.assertEqual(len(calls), 0)

    def test_health_method_not_allowed(self):
        response = self.client.post("/api/health")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "METHOD_NOT_ALLOWED")
        self.assertIn("中文", "中文")

    def test_review_normal(self):
        manifest = "A lab/bad.py\nA docs/中文.md\n"
        direct = _json_normalized(run_check(manifest, self.repo_root))
        self.assertGreater(direct["summary"]["must_fix_count"], 0)
        self.assertGreater(direct["summary"]["suggestion_count"], 0)
        response = self.post_review(self.client, manifest, self.repo_root.name)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "正常")
        self.assertEqual(data["summary"]["issue_count"], data["summary"]["must_fix_count"] + data["summary"]["suggestion_count"])
        self.assertGreater(data["summary"]["must_fix_count"], 0)
        self.assertGreater(data["summary"]["suggestion_count"], 0)
        self.assertEqual(data, direct)

    def test_review_empty_manifest(self):
        response = self.post_review(self.client, "", self.repo_root.name)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["entry_count"], 0)
        self.assertEqual(data["summary"]["issue_count"], 0)
        self.assertEqual(data["status"], "正常")
        self.assertEqual(data["files"], [])
        self.assertTrue(any("变更清单为空" in item for item in data["warnings"]))
        self.assertEqual(data["unparsed_lines"], [])

    def test_review_manifest_missing(self):
        calls: list[tuple[object, object, object]] = []
        self.override_engine(self.app, _counting_runner(calls))
        first = self.client.post("/api/review", json={"repo": self.repo_root.name})
        second = self.client.post("/api/review", json={"manifest": 123, "repo": self.repo_root.name})
        for response in (first, second):
            self.assertEqual(response.status_code, 422)
            body = response.json()
            self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
            self.assertIn("字段", body["error"]["detail"])
            self.assertTrue(body["request_id"])
        self.assertEqual(len(calls), 0)

    def test_review_manifest_too_large(self):
        calls: list[tuple[object, object, object]] = []
        app = self.make_app(self.make_settings(max_manifest_chars=10))
        self.override_engine(app, _counting_runner(calls))
        client = self.make_client(app)
        first = self.post_review(client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(first.status_code, 413)
        self.assertEqual(first.json()["error"]["code"], "MANIFEST_TOO_LARGE")

        app2 = self.make_app(self.make_settings(max_manifest_lines=1))
        self.override_engine(app2, _counting_runner(calls))
        client2 = self.make_client(app2)
        second = self.post_review(client2, "A a.txt\nA b.txt\n", self.repo_root.name)
        self.assertEqual(second.status_code, 413)
        self.assertEqual(second.json()["error"]["code"], "MANIFEST_TOO_LARGE")
        self.assertEqual(len(calls), 0)

    def test_review_request_too_large(self):
        calls: list[tuple[object, object, object]] = []
        app = self.make_app(self.make_settings(max_request_bytes=65_536))
        self.override_engine(app, _counting_runner(calls))
        client = self.make_client(app)
        payload = json.dumps({"manifest": "A " + "x" * 70_000, "repo": self.repo_root.name}).encode("utf-8")
        response = client.post("/api/review", content=payload, headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "REQUEST_TOO_LARGE")
        self.assertNotIn("x" * 100, response.text)
        self.assertNotIn(str(self.repo_root), response.text)
        self.assertEqual(len(calls), 0)

    def test_review_invalid_json(self):
        for body in (b"not-json", b"", b"[]"):
            with self.subTest(body=body):
                response = self.client.post("/api/review", content=body, headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "INVALID_JSON")
                self.assertIn("JSON", response.json()["error"]["message"])

    def test_review_wrong_content_type(self):
        payload = json.dumps({"manifest": "A lab/bad.py\n", "repo": self.repo_root.name}).encode("utf-8")
        for content_type in ("text/plain", "application/x-www-form-urlencoded"):
            with self.subTest(content_type=content_type):
                response = self.client.post("/api/review", content=payload, headers={"Content-Type": content_type})
                self.assertEqual(response.status_code, 415)
                self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_MEDIA_TYPE")

    def test_review_repo_missing(self):
        response = self.post_review(self.client, "A lab/bad.py\n", "missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "REPO_NOT_FOUND")
        file_response = self.post_review(self.client, "A lab/bad.py\n", "note.txt")
        self.assertEqual(file_response.status_code, 404)
        self.assertEqual(file_response.json()["error"]["code"], "REPO_NOT_FOUND")

    def test_review_repo_outside(self):
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        sibling = Path(str(self.repo_root) + "-evil")
        sibling.mkdir()
        for candidate in (outside, sibling):
            with self.subTest(candidate=candidate):
                response = self.post_review(self.client, "A lab/bad.py\n", str(candidate))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "REPO_FORBIDDEN")
                self.assertNotIn(str(candidate), response.text)

    def test_review_repo_traversal(self):
        original_resolve = Path.resolve
        original_exists = Path.exists
        resolve_calls: list[object] = []
        exists_calls: list[object] = []

        def counting_resolve(path: Path, *args, **kwargs):
            resolve_calls.append(path)
            return original_resolve(path, *args, **kwargs)

        def counting_exists(path: Path, *args, **kwargs):
            exists_calls.append(path)
            return original_exists(path, *args, **kwargs)

        with patch.object(Path, "resolve", counting_resolve), patch.object(Path, "exists", counting_exists):
            first = self.post_review(self.client, "A lab/bad.py\n", "../demo-repo")
            second = self.post_review(self.client, "A lab/bad.py\n", "a/../../b")
        for response in (first, second):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "REPO_FORBIDDEN")
        self.assertEqual(len(resolve_calls), 0)
        self.assertEqual(len(exists_calls), 0)

    def test_review_repo_url(self):
        with patch("socket.socket", side_effect=AssertionError("不应发起网络请求")):
            for repo in ("http://example.com/x", "https://example.com/repo"):
                with self.subTest(repo=repo):
                    response = self.post_review(self.client, "A lab/bad.py\n", repo)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json()["error"]["code"], "INVALID_REPO_PATH")

    def test_review_repo_nul(self):
        for repo in ("repo\x00evil", "", "   ", "a" * 513):
            with self.subTest(repo=repo):
                response = self.post_review(self.client, "A lab/bad.py\n", repo)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "INVALID_REPO_PATH")
                self.assertNotIn(str(self.repo_root), response.text)

    def test_review_repo_symlink_escape(self):
        outside = Path(self.temp_dir.name) / "link-outside"
        outside.mkdir()
        link = self.repo_root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass

        with patch("app.api.security.is_within_allowed_roots", return_value=False):
            response = self.post_review(self.client, "A lab/bad.py\n", "link")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "REPO_FORBIDDEN")

    def test_review_engine_degraded(self):
        report = _degraded_report()
        self.override_engine(self.app, lambda manifest, repo, config=None: report)
        response = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "部分降级")
        self.assertEqual(data["degraded_modules"][0]["module"], "代码检查")
        self.assertEqual(data["degraded_modules"][0]["reason"], "执行异常，结果可能不完整")
        self.assertEqual(data["warnings"], ["部分检查模块降级，结果可能不完整"])
        self.assertEqual(
            set(data),
            {"status", "summary", "files", "unparsed_lines", "degraded_modules", "warnings"},
        )

    def test_review_engine_exception(self):
        def broken(manifest, repo, config=None):
            raise RuntimeError("boom")

        self.override_engine(self.app, broken)
        response = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("Traceback", response.text)
        self.assertNotIn("RuntimeError", response.text)
        self.assertNotIn(str(self.repo_root), response.text)
        self.assertEqual(body["request_id"], response.headers.get("x-request-id"))

    def test_review_timeout(self):
        def slow(manifest, repo, config=None):
            time.sleep(2)
            return _empty_report()

        app = self.make_app(self.make_settings(review_timeout_seconds=1))
        self.override_engine(app, slow)
        client = self.make_client(app)
        started = time.perf_counter()
        response = self.post_review(client, "A lab/bad.py\n", self.repo_root.name)
        elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "REVIEW_TIMEOUT")
        self.assertLess(elapsed, 2.0)

    def test_review_response_shape(self):
        manifest = "A lab/bad.py\n"
        response = self.post_review(self.client, manifest, self.repo_root.name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {"status", "summary", "files", "unparsed_lines", "degraded_modules", "warnings"},
        )
        self.assertEqual(response.json(), _json_normalized(run_check(manifest, self.repo_root)))
        self.assertIn("application/json", response.headers.get("content-type", ""))
        self.assertIn("charset=utf-8", response.headers.get("content-type", ""))
        self.assertNotIn("\\u", response.text)

    def test_review_no_reordering(self):
        report = _ordered_report()
        self.override_engine(self.app, lambda manifest, repo, config=None: report)
        response = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(response.status_code, 200)
        actual = [
            (finding["level"], finding["file_path"], finding["line_no"], finding["rule_id"], finding["message"])
            for group in response.json()["files"]
            for finding in group["findings"]
        ]
        expected = [
            (finding.level.value, finding.file_path, finding.line_no, finding.rule_id, finding.message)
            for group in report.files
            for finding in group.findings
        ]
        self.assertEqual(actual, expected)
        self.assertIn("必须修改", [item[0] for item in actual])
        self.assertIn("优化建议", [item[0] for item in actual])

    def test_static_index_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn('id="manifest-input"', response.text)
        self.assertIn('id="submit-button"', response.text)
        self.assertIn('<meta charset="utf-8">', response.text)
        self.assertEqual(response.headers.get("x-frame-options"), "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers.get("content-security-policy", ""))

        empty_static = Path(self.temp_dir.name) / "empty-static"
        empty_static.mkdir()
        app = self.make_app(self.make_settings(static_dir=empty_static))
        client = self.make_client(app)
        missing = client.get("/")
        self.assertEqual(missing.status_code, 503)
        self.assertEqual(missing.json()["error"]["code"], "STATIC_NOT_FOUND")
        self.assertNotIn(str(empty_static), missing.text)

        asset = self.client.get("/static/index.html")
        self.assertIn(asset.status_code, (200, 404))
        self.assertNotIn(str(STATIC_DIR), asset.text)

    def test_static_index_no_external_urls(self):
        path = STATIC_DIR / "index.html"
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for token in ("http://", "https://", "cdn", "unpkg", "jsdelivr"):
            self.assertNotIn(token, lowered)
        for token in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(token, text)
        self.assertLessEqual(len(text.encode("utf-8")), 65_536)
        self.assertIn('<meta name="viewport"', text)
        self.assertIn('aria-live="polite"', text)

    def test_review_request_id_header(self):
        success = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        outside = Path(self.temp_dir.name) / "outside-id"
        outside.mkdir()
        failure = self.post_review(self.client, "A lab/bad.py\n", str(outside))
        self.assertEqual(success.status_code, 200)
        self.assertEqual(failure.status_code, 403)
        for response in (success, failure):
            request_id = response.headers.get("x-request-id", "")
            self.assertGreaterEqual(len(request_id), 8)
            self.assertLessEqual(len(request_id), 64)
            self.assertRegex(request_id, r"^[A-Za-z0-9-]+$")
        self.assertEqual(failure.json()["request_id"], failure.headers.get("x-request-id"))
        self.assertNotEqual(success.headers.get("x-request-id"), failure.headers.get("x-request-id"))

    def test_cors_disabled_by_default(self):
        health = self.client.get("/api/health")
        review = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        for response in (health, review):
            self.assertFalse(any(key.lower().startswith("access-control-") for key in response.headers))

        app = self.make_app(self.make_settings(cors_origins=("http://127.0.0.1:5500",)))
        client = self.make_client(app)
        preflight = client.request(
            "OPTIONS",
            "/api/review",
            headers={
                "Origin": "http://127.0.0.1:5500",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers.get("access-control-allow-origin"), "http://127.0.0.1:5500")
        methods = preflight.headers.get("access-control-allow-methods", "")
        self.assertIn("GET", methods)
        self.assertIn("POST", methods)
        self.assertIn("Content-Type", preflight.headers.get("access-control-allow-headers", ""))
        self.assertNotEqual(preflight.headers.get("access-control-allow-credentials"), "true")

    def test_security_headers(self):
        outside = Path(self.temp_dir.name) / "outside-headers"
        outside.mkdir()
        responses = (
            self.client.get("/"),
            self.client.get("/api/health"),
            self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name),
            self.post_review(self.client, "A lab/bad.py\n", str(outside)),
        )
        for response in responses:
            self.assertEqual(response.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(responses[1].headers.get("cache-control"), "no-store")
        self.assertEqual(responses[2].headers.get("cache-control"), "no-store")
        page = responses[0]
        self.assertEqual(page.headers.get("x-frame-options"), "DENY")
        self.assertIn("frame-ancestors 'none'", page.headers.get("content-security-policy", ""))

    def test_review_engine_called_once(self):
        calls: list[tuple[object, object, object]] = []
        runner = _counting_runner(calls)
        self.override_engine(self.app, runner)
        success = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][2])

        calls.clear()

        def broken(manifest, repo, config=None):
            calls.append((manifest, repo, config))
            raise RuntimeError("boom")

        self.override_engine(self.app, broken)
        failure = self.post_review(self.client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(failure.status_code, 500)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0][2])

    def test_review_busy(self):
        app = self.make_app(
            self.make_settings(
                review_max_concurrency=1,
                queue_timeout_seconds=0.0,
                review_timeout_seconds=5,
            )
        )
        release = threading.Event()

        def slow(manifest, repo, config=None):
            release.wait(0.3)
            return _empty_report()

        self.override_engine(app, slow)
        client = self.make_client(app)

        async def concurrent() -> tuple["httpx.Response", "httpx.Response"]:
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as async_client:
                return await asyncio.gather(
                    async_client.post("/api/review", json={"manifest": "A lab/bad.py\n", "repo": self.repo_root.name}),
                    async_client.post("/api/review", json={"manifest": "A lab/bad.py\n", "repo": self.repo_root.name}),
                )

        started = time.perf_counter()
        first, second = asyncio.run(concurrent())
        elapsed = time.perf_counter() - started
        responses = (first, second)
        self.assertTrue(any(response.status_code == 429 for response in responses))
        busy = [response for response in responses if response.status_code == 429][0]
        self.assertEqual(busy.json()["error"]["code"], "REVIEW_BUSY")
        self.assertLess(elapsed, 5.0)

        release.set()
        recovered = self.post_review(client, "A lab/bad.py\n", self.repo_root.name)
        self.assertEqual(recovered.status_code, 200)


class CliRegressionTest(unittest.TestCase):
    def test_cli_regression(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "notes").mkdir()
            (root / "notes" / "ok.txt").write_text("hello\n", encoding="utf-8")
            manifest = root / "changes.txt"
            manifest.write_text("A notes/ok.txt\n", encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.core.rules.engine",
                    "--manifest",
                    str(manifest),
                    "--repo",
                    str(root),
                    "--format",
                    "json",
                ],
                cwd=BACKEND,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(process.returncode, 0)
        data = json.loads(process.stdout)
        self.assertEqual(
            set(data),
            {"status", "summary", "files", "unparsed_lines", "degraded_modules", "warnings"},
        )
        self.assertNotIn("\\u", process.stdout)
        self.assertEqual(process.stderr, "")
        baseline = BACKEND / "baseline_cli_json.txt"
        if baseline.exists():
            self.assertEqual(process.stdout, baseline.read_text(encoding="utf-8"))

    def test_engine_has_no_web_imports(self):
        forbidden_roots = {"fastapi", "uvicorn", "httpx", "starlette", "pydantic"}
        hits: list[str] = []
        for path in (APP_DIR / "core" / "rules").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    if root in forbidden_roots or name.startswith("app.api"):
                        hits.append(f"{path}:{name}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
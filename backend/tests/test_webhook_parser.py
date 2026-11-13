from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.api.settings import WebSettings
from app.core.rules.common.models import ChangeStatus, FileGroup, ReportStatus, build_report
from app.integrations.models import OpenApiMode, OpenApiProfile
from app.webhook.app import create_webhook_app
from app.webhook.models import ChangedFilesSource, EventKind
from app.webhook.parser import (
    EventParseError,
    build_manifest,
    classify_event_kind,
    decode_json_object,
    extract_changed_files,
    extract_changed_files_with_statuses,
    normalize_changed_path,
    normalize_event,
    parse_event,
    should_fetch_via_openapi,
    should_fetch_via_openapi_values,
)
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import WebhookASGIClient, make_headers, make_payload, no_network

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _payload(*, event_id: str, **kwargs: object) -> dict[str, object]:
    payload = make_payload(**kwargs)
    payload["event_id"] = event_id
    return payload


def _root(temp: str) -> Path:
    path = Path(temp) / "lab-01"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings(root: Path) -> WebSettings:
    return WebSettings(allowed_repo_roots=(root.resolve(),), default_repo=root.name, static_dir=root)


def _clean_report():
    return build_report(status=ReportStatus.OK, files=(FileGroup("main.py", ChangeStatus.MODIFY),))


class _CountingRunner:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls.append((manifest_text, repo_root, config))
        return _clean_report()


class _CountingAdapter:
    def __init__(self) -> None:
        self.comments: list[object] = []

    def fetch_changed_files(self, repo: str, base_sha: str, head_sha: str):
        return None

    def publish_comment(self, repo: str, pr_number: int, payload):
        self.comments.append(payload)
        from app.integrations.models import PublishResult

        return PublishResult(True, 201, comment_id="mock-1")


class ParserTest(unittest.TestCase):
    def test_json_invalid(self):
        cases = (
            (b"", "事件内容为空"),
            (b"{not-json", "事件内容不是合法 JSON"),
            (b"[1, 2, 3]", "事件内容顶层必须是 JSON 对象"),
            (b"\xff\xfe", "事件内容不是合法 UTF-8"),
        )
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(EventParseError) as context:
                    decode_json_object(raw)
                self.assertEqual(context.exception.code, "WEBHOOK_INVALID_JSON")
                self.assertEqual(context.exception.status_code, 400)
                self.assertEqual(context.exception.message, message)

    def test_content_type_rejected(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            consumed: list[int] = []

            async def body_stream():
                for chunk in (b"{}",):
                    consumed.append(len(chunk))
                    yield chunk

            headers = make_headers(secret, b"{}")
            headers["Content-Type"] = "text/plain"
            try:
                response = WebhookASGIClient(app).post(config.path, content=body_stream(), headers=headers)
                self.assertEqual(response.status_code, 415)
                self.assertEqual(response.json()["error"]["code"], "WEBHOOK_UNSUPPORTED_MEDIA_TYPE")
                self.assertEqual(consumed, [])
                self.assertEqual(runner.calls, [])
            finally:
                service.shutdown(2.0)

    def test_payload_too_large_content_length(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, max_body_bytes=65_536, queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            headers = make_headers(secret, b"")
            headers["Content-Type"] = "application/json"
            try:
                response = WebhookASGIClient(app).post(config.path, content=b"x" * 70_000, headers=headers)
                self.assertEqual(response.status_code, 413)
                error = response.json()["error"]
                self.assertEqual(error["code"], "WEBHOOK_PAYLOAD_TOO_LARGE")
                self.assertEqual(error["message"], "事件内容过大")
                self.assertEqual(runner.calls, [])
            finally:
                service.shutdown(2.0)

    def test_payload_too_large_chunked(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, max_body_bytes=65_536, queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            consumed: list[int] = []

            async def body_stream():
                for _ in range(9):
                    chunk = b"x" * 8_192
                    consumed.append(len(chunk))
                    yield chunk

            headers = make_headers(secret, b"")
            headers["Content-Type"] = "application/json"
            try:
                response = WebhookASGIClient(app).post(config.path, content=body_stream(), headers=headers)
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.json()["error"]["code"], "WEBHOOK_PAYLOAD_TOO_LARGE")
                self.assertEqual(sum(consumed), 73_728)
                self.assertGreater(sum(consumed), config.max_body_bytes)
                self.assertEqual(runner.calls, [])
            finally:
                service.shutdown(2.0)

    def test_event_type_allowed(self):
        config = WebhookConfig()
        self.assertIs(classify_event_kind("pr.created", config), EventKind.CREATED)
        self.assertIs(classify_event_kind("MR.CREATED", config), EventKind.CREATED)
        self.assertIs(classify_event_kind("pr.updated", config), EventKind.UPDATED)
        self.assertIs(classify_event_kind("pr.synchronize", config), EventKind.UPDATED)
        custom = WebhookConfig(event_kind_map={"deploy.finished": "updated"})
        self.assertIs(classify_event_kind("deploy.finished", custom), EventKind.UPDATED)
        self.assertIsNone(classify_event_kind("pr.closed", config))

    def test_event_type_ignored(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            adapter = _CountingAdapter()
            service = WebhookService(config, _settings(root), runner=runner, adapter=adapter)
            app = create_webhook_app(config, service=service)
            payload = _payload(repo=root.name, event_id="evt-w18", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = make_headers(secret, raw, event_type="pr.reopened")
            headers["Content-Type"] = "application/json"
            try:
                response = WebhookASGIClient(app).post(config.path, content=raw, headers=headers)
                self.assertEqual(response.status_code, 202)
                body = response.json()
                self.assertEqual(body["status"], "ignored")
                self.assertEqual(body["action"], "skipped")
                self.assertEqual(runner.calls, [])
                self.assertEqual(adapter.comments, [])
            finally:
                service.shutdown(2.0)

    def test_event_invalid_missing_pr(self):
        secret = os.urandom(16).hex()
        payload = _payload(repo="lab-01", event_id="evt-w19")
        payload.pop("pull_request")
        payload["changed_files"] = ["main.py"]
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        config = WebhookConfig(secret=secret)
        with self.assertRaises(EventParseError) as context:
            parse_event(raw, make_headers(secret, raw), config)
        error = context.exception
        self.assertEqual(error.code, "WEBHOOK_EVENT_INVALID")
        self.assertEqual(error.status_code, 422)
        self.assertEqual(error.message, "事件字段不合法")
        self.assertEqual(error.detail, "字段：pull_request_number")

    def test_field_map_custom(self):
        secret = os.urandom(16).hex()
        field_map = {
            "event_id": ("meta.id",),
            "repository": ("meta.repo",),
            "pull_request_number": ("meta.pr",),
            "base_sha": ("meta.base",),
            "head_sha": ("meta.head",),
            "action": ("meta.action",),
            "changed_files": ("meta.files",),
        }
        payload = {
            "meta": {
                "id": "evt-custom-9",
                "repo": "acme/custom",
                "pr": 77,
                "base": "a" * 40,
                "head": "b" * 40,
                "action": "opened",
                "files": ["src/a.py"],
            },
            "event_id": "evt-default-must-be-ignored",
            "repository": {"full_name": "default/repo"},
            "pull_request": {"number": 1},
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        config = WebhookConfig(secret=secret, field_map=field_map)
        event = parse_event(raw, make_headers(secret, raw), config)
        self.assertEqual(event.event_id, "evt-custom-9")
        self.assertEqual(event.event_id_source, "payload")
        self.assertEqual(event.repository_identifier, "acme/custom")
        self.assertEqual(event.pull_request_number, 77)
        self.assertEqual(event.base_sha, "a" * 40)
        self.assertEqual(event.head_sha, "b" * 40)
        self.assertEqual(event.action, "opened")
        normalized = normalize_event(event, config, "lab-01")
        self.assertIs(normalized.changed_files_source, ChangedFilesSource.PAYLOAD)
        self.assertEqual(normalized.changed_files, ("src/a.py",))

    def test_event_id_fallback_delivery_header(self):
        secret = os.urandom(16).hex()
        payload = {
            "repository": {"full_name": "acme/lab-01"},
            "pull_request": {"number": 12},
            "changed_files": ["main.py"],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = make_headers(secret, raw, delivery_id="delivery-777")
        event = parse_event(raw, headers, WebhookConfig(secret=secret))
        self.assertEqual(event.event_id, "delivery-777")
        self.assertEqual(event.event_id_source, "delivery_header")

    def test_event_id_fallback_content_hash(self):
        secret = os.urandom(16).hex()
        payload = {
            "repository": {"full_name": "acme/lab-01"},
            "pull_request": {"number": 12},
            "changed_files": ["main.py"],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        config = WebhookConfig(secret=secret)
        first = parse_event(raw, make_headers(secret, raw), config)
        second = parse_event(raw, make_headers(secret, raw), config)
        self.assertEqual(first.event_id_source, "content_hash")
        self.assertEqual(second.event_id_source, "content_hash")
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(len(first.event_id), 64)
        int(first.event_id, 16)
        self.assertEqual(first.event_id, first.event_id.lower())

    def test_changed_files_from_payload(self):
        raw = _fixture("webhook_pr_created.json")
        config = WebhookConfig(secret="fake")
        event = parse_event(raw, make_headers("fake", raw), config)
        normalized = normalize_event(event, config, "lab-01")
        self.assertIs(normalized.changed_files_source, ChangedFilesSource.PAYLOAD)
        self.assertTrue(normalized.changed_files_available)
        self.assertEqual(normalized.changed_files, ("lab/main.py", "docs/lab01.md"))
        self.assertEqual(normalized.illegal_paths, ())
        self.assertFalse(should_fetch_via_openapi(normalized, config))

    def test_changed_files_from_lists(self):
        raw = _fixture("webhook_pr_updated.json")
        config = WebhookConfig(secret="fake")
        payload = json.loads(raw.decode("utf-8"))
        paths, source, statuses, illegal = extract_changed_files_with_statuses(payload, config)
        self.assertIs(source, ChangedFilesSource.PAYLOAD_LISTS)
        self.assertEqual(paths, ("lab/new_demo.py", "lab/main.py", "lab/old_demo.py"))
        self.assertEqual(statuses["lab/new_demo.py"], "A")
        self.assertEqual(statuses["lab/main.py"], "M")
        self.assertEqual(statuses["lab/old_demo.py"], "D")
        self.assertEqual(illegal, ())

        payload["added_files"].append("lab/main.py")
        _, _, merged, _ = extract_changed_files_with_statuses(payload, config)
        self.assertEqual(merged["lab/main.py"], "A")

    def test_changed_files_from_openapi(self):
        raw = _fixture("webhook_changed_files_missing.json")
        profile = OpenApiProfile(
            base_url="https://api.example.invalid",
            comment_endpoint_template="/repos/{repo}/pulls/{pr_number}/comments",
            changed_files_endpoint_template="/repos/{repo}/compare/{base_sha}/{head_sha}",
            body_template='{"body": {markdown}}',
            allowed_hosts=("api.example.invalid",),
        )
        config = WebhookConfig(secret="fake", openapi_mode=OpenApiMode.MOCK, openapi_profile=profile)
        payload = json.loads(raw.decode("utf-8"))
        self.assertTrue(should_fetch_via_openapi_values(payload, config))
        paths, source = extract_changed_files(payload, config)
        self.assertEqual(paths, ())
        self.assertIs(source, ChangedFilesSource.OPENAPI)
        event = parse_event(raw, make_headers("fake", raw), config)
        normalized = normalize_event(event, config, "lab-01")
        self.assertIs(normalized.changed_files_source, ChangedFilesSource.OPENAPI)
        self.assertFalse(normalized.changed_files_available)
        self.assertTrue(should_fetch_via_openapi(normalized, config))

    def test_changed_files_unavailable(self):
        raw = _fixture("webhook_changed_files_missing.json")
        config = WebhookConfig(secret="fake")
        payload = json.loads(raw.decode("utf-8"))
        self.assertFalse(should_fetch_via_openapi_values(payload, config))
        paths, source = extract_changed_files(payload, config)
        self.assertEqual(paths, ())
        self.assertIs(source, ChangedFilesSource.NONE)
        event = parse_event(raw, make_headers("fake", raw), config)
        normalized = normalize_event(event, config, "lab-01")
        self.assertIs(normalized.changed_files_source, ChangedFilesSource.NONE)
        self.assertFalse(normalized.changed_files_available)
        self.assertFalse(should_fetch_via_openapi(normalized, config))

    def test_illegal_paths_filtered(self):
        payload = {
            "changed_files": [
                "..\\secret.txt",
                "/etc/passwd",
                "C:\\windows\\system32\\x.dll",
                "\\\\server\\share\\x.txt",
                "./ok.py",
                "a//b.py",
            ]
        }
        config = WebhookConfig()
        paths, source, statuses, illegal = extract_changed_files_with_statuses(payload, config)
        self.assertIs(source, ChangedFilesSource.PAYLOAD)
        self.assertEqual(paths, ("ok.py", "a/b.py"))
        self.assertEqual(statuses, {"ok.py": "M", "a/b.py": "M"})
        self.assertEqual(len(illegal), 4)
        self.assertEqual(normalize_changed_path("..\\secret.txt"), (None, "路径越界"))
        self.assertEqual(normalize_changed_path("/etc/passwd"), (None, "绝对路径"))
        self.assertEqual(normalize_changed_path("C:\\x"), (None, "绝对路径"))
        self.assertEqual(normalize_changed_path("\\\\server\\share\\x"), (None, "UNC 或设备路径"))
        self.assertEqual(normalize_changed_path("   "), (None, "空路径"))
        self.assertEqual(normalize_changed_path("a\\b\\c.py"), ("a/b/c.py", None))

    def test_manifest_construction(self):
        text, count = build_manifest(
            ["a.py", "b c.py", "d.py"],
            {"a.py": "A", "b c.py": "M", "d.py": "D"},
        )
        self.assertEqual(text, "A a.py\nM b c.py\nD d.py\n")
        self.assertEqual(count, 3)
        self.assertEqual(len(text.splitlines()), count)
        self.assertIn("M b c.py", text)
        text_unknown, count_unknown = build_manifest(["e.py"], {"e.py": "X"})
        self.assertEqual(text_unknown, "M e.py\n")
        self.assertEqual(count_unknown, 1)
        config = WebhookConfig(max_changed_files=2)
        self.assertGreater(count, config.max_changed_files)
        empty_text, empty_count = build_manifest([])
        self.assertEqual(empty_text, "")
        self.assertEqual(empty_count, 0)


if __name__ == "__main__":
    unittest.main()
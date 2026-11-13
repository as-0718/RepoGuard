from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import httpx

from app.api.settings import WebSettings
from app.core.rules.common.models import ChangeStatus, FileGroup, ReportStatus, build_report
from app.integrations.client import HttpxHttpClient
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import AuthScheme, OpenApiMode, OpenApiProfile, PublishResult, validate_profile
from app.integrations.openapi import ConfigurableOpenApiAdapter
from app.webhook.app import create_webhook_app
from app.webhook.models import CommentPayload
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import WebhookASGIClient, make_headers, make_payload, no_network

MARKER = "<!-- repoguard:event:evt-openapi -->"


def _root(temp: str) -> Path:
    path = Path(temp) / "lab-01"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings(root: Path) -> WebSettings:
    return WebSettings(allowed_repo_roots=(root.resolve(),), default_repo=root.name, static_dir=root)


def _event_payload(*, event_id: str, **kwargs: object) -> dict[str, object]:
    payload = make_payload(**kwargs)
    payload["event_id"] = event_id
    return payload


def _clean_report():
    return build_report(status=ReportStatus.OK, files=(FileGroup("main.py", ChangeStatus.MODIFY),))


class _CountingRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls += 1
        return _clean_report()


def _payload() -> CommentPayload:
    markdown = "## RepoGuard 检查结果\n\n正文\n\n" + MARKER
    return CommentPayload(
        event_id="evt-openapi",
        repo_label="lab-01",
        pull_request_number=12,
        markdown=markdown,
        char_count=len(markdown),
        byte_count=len(markdown.encode("utf-8")),
        truncated=False,
        omitted_must_fix=0,
        omitted_suggestions=0,
        marker=MARKER,
        check_status="正常",
        must_fix_count=0,
        suggestion_count=0,
        issue_count=0,
        skipped_file_count=0,
        degraded_module_count=0,
    )


def _profile(**overrides) -> OpenApiProfile:
    values = {
        "base_url": "https://api.example.invalid",
        "comment_endpoint_template": "/repos/{repo}/pulls/{pr_number}/comments",
        "body_template": '{"body": {markdown}}',
        "allowed_hosts": ("api.example.invalid",),
        "auth_scheme": AuthScheme.BEARER,
        "token_env": "REPOGUARD_TEST_TOKEN",
        "max_retries": 2,
        "backoff_base_seconds": 0.5,
        "timeout_seconds": 10.0,
        "follow_redirects": False,
        "comment_marker_template": "<!-- repoguard:event:{event_id} -->",
    }
    values.update(overrides)
    return OpenApiProfile(**values)


def _adapter(handler, sleeps: list[float], profile: OpenApiProfile | None = None) -> ConfigurableOpenApiAdapter:
    client = HttpxHttpClient(transport=httpx.MockTransport(handler))
    return ConfigurableOpenApiAdapter(
        profile or _profile(),
        client=client,
        clock=lambda: 0.0,
        sleeper=sleeps.append,
        env={},
        token="fake-token",
    )


def _headers(secret: str, raw: bytes) -> dict[str, str]:
    headers = make_headers(secret, raw)
    headers["Content-Type"] = "application/json"
    return headers


class OpenApiTest(unittest.TestCase):
    def test_openapi_disabled_no_request(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, sync_mode=True, openapi_mode=OpenApiMode.DISABLED)
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=_CountingRunner(), adapter=adapter)
            app = create_webhook_app(config, service=service)
            payload = _event_payload(repo=root.name, event_id="evt-w50", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = WebhookASGIClient(app).post(config.path, content=raw, headers=_headers(secret, raw))
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "degraded")
            record = service.recent_records(1)[0]
            self.assertEqual(record.delivery_status, "skipped")
            self.assertEqual(record.reason, "OpenAPI 未启用")
            self.assertEqual(adapter.requests, ())

    def test_openapi_mock_delivered(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, sync_mode=True, openapi_mode=OpenApiMode.MOCK)
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=_CountingRunner(), adapter=adapter)
            app = create_webhook_app(config, service=service)
            payload = _event_payload(repo=root.name, event_id="evt-w51", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = WebhookASGIClient(app).post(config.path, content=raw, headers=_headers(secret, raw))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "completed")
            record = service.recent_records(1)[0]
            self.assertEqual(record.delivery_status, "mock_delivered")
            self.assertEqual(len(adapter.comments), 1)
            self.assertTrue(adapter.comments[0].markdown.endswith(adapter.comments[0].marker))

    def test_openapi_timeout_retry(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.TimeoutException("timeout")

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 3)
        self.assertEqual(result.attempts, 3)
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "OPENAPI_TIMEOUT")
        self.assertTrue(result.retried)
        self.assertEqual(len(sleeps), 2)
        self.assertGreaterEqual(sleeps[0], 0.5 * 0.8)
        self.assertLessEqual(sleeps[0], 0.5 * 1.2)
        self.assertGreaterEqual(sleeps[1], 1.0 * 0.8)
        self.assertLessEqual(sleeps[1], 1.0 * 1.2)

    def test_openapi_429_retry(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, json={"message": "busy"})
            return httpx.Response(201, json={"data": {"id": "c-1"}})

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 2)
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertTrue(result.retried)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.comment_id, "c-1")
        self.assertEqual(len(sleeps), 1)

    def test_openapi_5xx_retry_then_fail(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(503, json={"message": "down"})

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 3)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.error_code, "OPENAPI_UNAVAILABLE")
        self.assertTrue(result.retried)
        self.assertIsNone(result.comment_id)

    def test_openapi_401_no_retry(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(401, json={"message": "unauthorized"})

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 1)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error_code, "OPENAPI_AUTH_FAILED")
        self.assertFalse(result.retried)
        self.assertEqual(sleeps, [])

    def test_openapi_404_no_retry(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(404, json={"message": "missing"})

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 1)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error_code, "OPENAPI_NOT_FOUND")
        self.assertEqual(sleeps, [])

    def test_openapi_live_incomplete(self):
        profile = OpenApiProfile(base_url="https://api.example.invalid")
        missing = validate_profile(profile, OpenApiMode.LIVE)
        self.assertIn("comment_endpoint_template", missing)
        self.assertIn("body_template", missing)
        self.assertIn("allowed_hosts", missing)
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(
                secret=secret,
                sync_mode=True,
                openapi_mode=OpenApiMode.LIVE,
                openapi_profile=profile,
            )
            service = WebhookService(config, _settings(root), runner=_CountingRunner())
            self.assertIsNone(service._adapter)
            app = create_webhook_app(config, service=service)
            health = WebhookASGIClient(app).get("/healthz")
            self.assertEqual(health.status_code, 503)
            health_body = health.json()
            self.assertEqual(health_body["status"], "degraded")
            self.assertEqual(health_body["openapi_mode"], "live")
            payload = _event_payload(repo=root.name, event_id="evt-w57", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = WebhookASGIClient(app).post(config.path, content=raw, headers=_headers(secret, raw))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "OPENAPI_NOT_CONFIGURED")

    def test_openapi_host_forbidden(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(201, json={"data": {"id": "c-1"}})

        profile = _profile(
            comment_endpoint_template="https://other.example.invalid/repos/{repo}/pulls/{pr_number}/comments"
        )
        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps, profile=profile)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(calls, [])
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "OPENAPI_HOST_FORBIDDEN")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(sleeps, [])

    def test_openapi_no_redirect(self):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://other.example.invalid/next"})

        sleeps: list[float] = []
        adapter = _adapter(handler, sleeps)
        result = adapter.publish_comment("acme/lab-01", 12, _payload())
        self.assertEqual(len(calls), 1)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error_code, "OPENAPI_REDIRECT_FORBIDDEN")
        self.assertFalse(result.retried)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
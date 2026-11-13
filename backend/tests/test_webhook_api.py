from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.app import create_app
from app.api.settings import WebSettings
from app.core.rules.common.models import ChangeStatus, FileGroup, ReportStatus, build_report
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import OpenApiMode, OpenApiProfile
from app.webhook.app import create_webhook_app
from app.webhook.service import EngineUnavailableError, WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import WebhookASGIClient, make_headers, make_payload, no_network

HEALTH_FIELDS = {
    "status",
    "service",
    "version",
    "secret_configured",
    "signature_algorithm",
    "openapi_mode",
    "engine",
    "queue_depth",
    "queue_capacity",
    "dedup_size",
    "allowed_repo_count",
    "recent_delivery_failures",
    "time",
}


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


class _CountingRunner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls += 1
        return _clean_report()


def _headers(secret: str, raw: bytes) -> dict[str, str]:
    headers = make_headers(secret, raw)
    headers["Content-Type"] = "application/json"
    return headers


class WebhookApiTest(unittest.TestCase):
    def test_health_ok(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            config = WebhookConfig(secret=os.urandom(16).hex(), queue_capacity=2, worker_concurrency=1)
            service = WebhookService(config, _settings(root), runner=_CountingRunner())
            app = create_webhook_app(config, service=service)
            response = WebhookASGIClient(app).get("/healthz")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(set(body), HEALTH_FIELDS)
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["service"], "repoguard-webhook")
            self.assertEqual(body["version"], "1.0.0")
            self.assertEqual(body["signature_algorithm"], "HMAC-SHA256")
            self.assertTrue(body["secret_configured"])
            self.assertEqual(body["openapi_mode"], "disabled")
            self.assertEqual(body["engine"], "available")
            self.assertEqual(body["queue_capacity"], 2)
            self.assertEqual(body["allowed_repo_count"], 1)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertTrue(response.headers["X-Request-ID"])

    def test_health_degraded(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)

            empty_secret = WebhookConfig(secret="", queue_capacity=2, worker_concurrency=1)
            service_secret = WebhookService(empty_secret, _settings(root), runner=_CountingRunner())
            app_secret = create_webhook_app(empty_secret, service=service_secret)
            response_secret = WebhookASGIClient(app_secret).get("/healthz")
            self.assertEqual(response_secret.status_code, 503)
            self.assertEqual(response_secret.json()["status"], "degraded")
            self.assertFalse(response_secret.json()["secret_configured"])

            engine_config = WebhookConfig(secret=os.urandom(16).hex(), queue_capacity=2, worker_concurrency=1)
            with patch("app.webhook.service.get_engine", side_effect=EngineUnavailableError("规则引擎当前不可用")):
                service_engine = WebhookService(engine_config, _settings(root))
            self.assertIsNone(service_engine._runner)
            app_engine = create_webhook_app(engine_config, service=service_engine)
            response_engine = WebhookASGIClient(app_engine).get("/healthz")
            self.assertEqual(response_engine.status_code, 503)
            self.assertEqual(response_engine.json()["status"], "degraded")
            self.assertEqual(response_engine.json()["engine"], "unavailable")

            live_config = WebhookConfig(
                secret=os.urandom(16).hex(),
                openapi_mode=OpenApiMode.LIVE,
                openapi_profile=OpenApiProfile(),
                queue_capacity=2,
                worker_concurrency=1,
            )
            service_live = WebhookService(live_config, _settings(root), runner=_CountingRunner())
            self.assertIsNone(service_live._adapter)
            app_live = create_webhook_app(live_config, service=service_live)
            response_live = WebhookASGIClient(app_live).get("/healthz")
            self.assertEqual(response_live.status_code, 503)
            self.assertEqual(response_live.json()["status"], "degraded")
            self.assertEqual(response_live.json()["openapi_mode"], "live")

    def test_health_method_not_allowed(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            config = WebhookConfig(secret=os.urandom(16).hex(), queue_capacity=2, worker_concurrency=1)
            service = WebhookService(config, _settings(root), runner=_CountingRunner())
            app = create_webhook_app(config, service=service)
            client = WebhookASGIClient(app)
            health_post = client.post("/healthz", content=b"{}", headers={"Content-Type": "application/json"})
            self.assertEqual(health_post.status_code, 405)
            self.assertEqual(health_post.json()["error"]["code"], "METHOD_NOT_ALLOWED")
            webhook_get = client.get("/webhook")
            self.assertEqual(webhook_get.status_code, 405)
            self.assertEqual(webhook_get.json()["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_phase2_routes_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            static_dir = Path(temp)
            app = create_app(
                WebSettings(
                    allowed_repo_roots=(),
                    default_repo=None,
                    static_dir=static_dir,
                )
            )
            paths = {route.path for route in app.routes}
            self.assertIn("/", paths)
            self.assertIn("/api/review", paths)
            self.assertIn("/api/health", paths)
            self.assertNotIn("/webhook", paths)
            self.assertNotIn("/healthz", paths)

    def test_cli_regression(self):
        backend_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contents = root / "notes"
            contents.mkdir(parents=True, exist_ok=True)
            (contents / "ok.txt").write_text("hello\n", encoding="utf-8")
            manifest = root / "changes.txt"
            manifest.write_text("A notes/ok.txt\n", encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if not key.startswith("REPOGUARD_")}
            result = subprocess.run(
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
                cwd=str(backend_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(
                set(data),
                {"status", "summary", "files", "unparsed_lines", "degraded_modules", "warnings"},
            )
            self.assertEqual(data["status"], "正常")
            self.assertEqual(data["summary"]["issue_count"], 0)
            self.assertNotIn("\\u", result.stdout)

    def test_no_network_outside_mock(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()

            disabled_config = WebhookConfig(
                secret=secret,
                sync_mode=True,
                openapi_mode=OpenApiMode.DISABLED,
                queue_capacity=2,
                worker_concurrency=1,
            )
            disabled_adapter = MockOpenApiAdapter()
            disabled_service = WebhookService(
                disabled_config,
                _settings(root),
                runner=_CountingRunner(),
                adapter=disabled_adapter,
            )
            disabled_app = create_webhook_app(disabled_config, service=disabled_service)
            payload = _payload(repo=root.name, event_id="evt-w65-disabled", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            disabled_response = WebhookASGIClient(disabled_app).post(
                disabled_config.path,
                content=raw,
                headers=_headers(secret, raw),
            )
            self.assertEqual(disabled_response.status_code, 202)
            self.assertEqual(disabled_adapter.requests, ())

            mock_config = WebhookConfig(
                secret=secret,
                sync_mode=True,
                openapi_mode=OpenApiMode.MOCK,
                queue_capacity=2,
                worker_concurrency=1,
            )
            mock_adapter = MockOpenApiAdapter()
            mock_service = WebhookService(mock_config, _settings(root), runner=_CountingRunner(), adapter=mock_adapter)
            mock_app = create_webhook_app(mock_config, service=mock_service)
            mock_payload = _payload(repo=root.name, event_id="evt-w65-mock", changed_files=["main.py"])
            mock_raw = json.dumps(mock_payload, ensure_ascii=False).encode("utf-8")
            mock_response = WebhookASGIClient(mock_app).post(
                mock_config.path,
                content=mock_raw,
                headers=_headers(secret, mock_raw),
            )
            self.assertEqual(mock_response.status_code, 200)
            self.assertEqual(len(mock_adapter.comments), 1)


if __name__ == "__main__":
    unittest.main()
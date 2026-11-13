from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from app.api.settings import WebSettings
from app.core.rules.common.models import ChangeStatus, FileGroup, ReportStatus, build_report
from app.webhook.app import create_webhook_app
from app.webhook.models import CheckOutcome
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from app.webhook.signature import (
    SignatureError,
    SignatureResult,
    build_signature,
    parse_signature_header,
    parse_timestamp,
    verify_signature,
)
from tests.webhook_helpers import (
    WebhookASGIClient,
    make_headers,
    make_signature,
    make_payload,
    no_network,
)

NOW = 1_700_000_000


def _body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _payload(*, event_id: str, **kwargs: object) -> dict[str, object]:
    payload = make_payload(**kwargs)
    payload["event_id"] = event_id
    return payload


def _headers(
    secret: str,
    raw: bytes,
    *,
    now: int = NOW,
    prefix: str = "sha256=",
    include_signature: bool = True,
    include_timestamp: bool = True,
    delivery_id: str | None = None,
) -> dict[str, str]:
    headers = make_headers(
        secret,
        raw,
        event_type="pr.created",
        timestamp=str(now),
        signature_prefix=prefix,
        delivery_id=delivery_id,
    )
    defaults = WebhookConfig()
    if not include_signature:
        headers.pop(defaults.signature_header, None)
    if not include_timestamp:
        headers.pop(defaults.timestamp_header, None)
    headers["Content-Type"] = "application/json"
    return headers


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
        self.calls: list[tuple[object, object, object]] = []

    def __call__(self, manifest_text, repo_root, config=None):
        self.calls.append((manifest_text, repo_root, config))
        return _clean_report()


class SignatureTest(unittest.TestCase):
    def test_signature_ok(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(secret=secret, queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            payload = _payload(repo=root.name, event_id="evt-w01", changed_files=["main.py"])
            raw = _body(payload)
            headers = _headers(secret, raw, now=int(time.time()))
            try:
                response = WebhookASGIClient(app).post(config.path, content=raw, headers=headers)
                self.assertEqual(response.status_code, 202)
                body = response.json()
                self.assertEqual(body["status"], "accepted")
                self.assertEqual(body["action"], "queued")
                self.assertFalse(body["duplicate"])
                self.assertEqual(body["event_id"], "evt-w01")
            finally:
                service.shutdown(2.0)

    def test_signature_missing(self):
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

            headers = _headers(secret, b"{}", include_signature=False, now=int(time.time()))
            try:
                response = WebhookASGIClient(app).post(config.path, content=body_stream(), headers=headers)
                self.assertEqual(response.status_code, 401)
                error = response.json()["error"]
                self.assertEqual(error["code"], "WEBHOOK_SIGNATURE_MISSING")
                self.assertIsNone(error["detail"])
                self.assertEqual(consumed, [])
            finally:
                service.shutdown(2.0)

    def test_signature_invalid(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w03"}'
        config = WebhookConfig(secret=secret)
        headers = _headers(os.urandom(16).hex(), raw)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, raw, config, now=NOW)
        error = context.exception
        self.assertEqual(error.code, "WEBHOOK_SIGNATURE_INVALID")
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.message, "Webhook 签名无效")
        self.assertIsNone(error.detail)

    def test_signature_body_tampered(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w04","value":"original"}'
        config = WebhookConfig(secret=secret)
        headers = _headers(secret, raw)
        tampered = raw[:-2] + b'X}'
        self.assertNotEqual(raw, tampered)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, tampered, config, now=NOW)
        self.assertEqual(context.exception.code, "WEBHOOK_SIGNATURE_INVALID")
        self.assertEqual(context.exception.status_code, 401)

    def test_signature_prefix_optional(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w05"}'
        bare = make_signature(secret, str(NOW), raw)
        bare_config = WebhookConfig(secret=secret, signature_prefix="")
        headers = _headers(secret, raw, prefix="")
        result = verify_signature(headers, raw, bare_config, now=NOW)
        self.assertTrue(result.ok)
        self.assertFalse(result.used_previous)

        prefixed_config = WebhookConfig(secret=secret)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, raw, prefixed_config, now=NOW)
        self.assertEqual(context.exception.code, "WEBHOOK_SIGNATURE_INVALID")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(bare, parse_signature_header(bare, ""))

    def test_signature_wrong_length(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w06"}'
        config = WebhookConfig(secret=secret)
        full = make_signature(secret, str(NOW), raw)
        for value in ("sha256=" + full[:-1], "sha256=" + full + "a"):
            headers = _headers(secret, raw)
            headers[config.signature_header] = value
            with self.subTest(length=len(value) - len("sha256=")):
                with self.assertRaises(SignatureError) as context:
                    verify_signature(headers, raw, config, now=NOW)
                self.assertEqual(context.exception.code, "WEBHOOK_SIGNATURE_INVALID")
                self.assertEqual(context.exception.status_code, 401)

    def test_timestamp_missing(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w07"}'
        config = WebhookConfig(secret=secret)
        headers = _headers(secret, raw, include_timestamp=False)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, raw, config, now=NOW)
        self.assertEqual(context.exception.code, "WEBHOOK_TIMESTAMP_MISSING")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.message, "缺少 Webhook 时间戳")

    def test_timestamp_expired(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w08"}'
        config = WebhookConfig(secret=secret)
        headers = _headers(secret, raw, now=NOW - 400)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, raw, config, now=NOW)
        self.assertEqual(context.exception.code, "WEBHOOK_TIMESTAMP_EXPIRED")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.message, "Webhook 时间戳已过期")

    def test_timestamp_future(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w09"}'
        config = WebhookConfig(secret=secret)
        headers = _headers(secret, raw, now=NOW + 400)
        with self.assertRaises(SignatureError) as context:
            verify_signature(headers, raw, config, now=NOW)
        self.assertEqual(context.exception.code, "WEBHOOK_TIMESTAMP_INVALID")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.message, "Webhook 时间戳不合法")

    def test_timestamp_millis(self):
        secret = os.urandom(16).hex()
        raw = b'{"event_id":"evt-w10"}'
        millis = NOW * 1000 + 123
        config = WebhookConfig(secret=secret)
        headers = _headers(secret, raw, now=int(millis))
        result = verify_signature(headers, raw, config, now=NOW)
        self.assertIsInstance(result, SignatureResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.timestamp_unit, "milliseconds")
        self.assertEqual(result.timestamp_seconds, int(millis) // 1000)
        self.assertEqual(result.skew_seconds, NOW - int(millis) // 1000)
        self.assertEqual(parse_timestamp(str(millis), NOW, 300)[2], "milliseconds")

    def test_secret_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            config = WebhookConfig(secret="", queue_capacity=2, worker_concurrency=1)
            runner = _CountingRunner()
            service = WebhookService(config, _settings(root), runner=runner)
            app = create_webhook_app(config, service=service)
            consumed: list[int] = []

            async def body_stream():
                for chunk in (b"{}",):
                    consumed.append(len(chunk))
                    yield chunk

            headers = _headers("", b"{}", now=int(time.time()))
            try:
                response = WebhookASGIClient(app).post(config.path, content=body_stream(), headers=headers)
                self.assertEqual(response.status_code, 503)
                error = response.json()["error"]
                self.assertEqual(error["code"], "WEBHOOK_SECRET_NOT_CONFIGURED")
                self.assertEqual(error["message"], "Webhook 签名密钥未配置")
                self.assertEqual(consumed, [])
            finally:
                service.shutdown(2.0)

    def test_secret_rotation_previous(self):
        current = os.urandom(16).hex()
        previous = os.urandom(16).hex()
        raw = _body(_payload(repo="lab-01", event_id="evt-w12-a", changed_files=["main.py"]))
        config = WebhookConfig(secret=current, secret_previous=previous)
        result = verify_signature(_headers(previous, raw), raw, config, now=NOW)
        self.assertTrue(result.ok)
        self.assertTrue(result.used_previous)
        self.assertEqual(result.timestamp_seconds, NOW)
        self.assertFalse(verify_signature(_headers(current, raw), raw, config, now=NOW).used_previous)
        expected = hmac.new(
            previous.encode("utf-8"),
            str(NOW).encode("utf-8") + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(hmac.compare_digest(expected, make_signature(previous, str(NOW), raw)))

        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            app_config = WebhookConfig(
                secret=current,
                secret_previous=previous,
                queue_capacity=2,
                worker_concurrency=1,
            )
            runner = _CountingRunner()
            service = WebhookService(app_config, _settings(root), runner=runner)
            app = create_webhook_app(app_config, service=service)
            current_raw = _body(_payload(repo=root.name, event_id="evt-w12-current", changed_files=["main.py"]))
            previous_raw = _body(_payload(repo=root.name, event_id="evt-w12-prev", changed_files=["main.py"]))
            try:
                current_response = WebhookASGIClient(app).post(
                    app_config.path,
                    content=current_raw,
                    headers=_headers(current, current_raw, now=int(time.time())),
                )
                previous_response = WebhookASGIClient(app).post(
                    app_config.path,
                    content=previous_raw,
                    headers=_headers(previous, previous_raw, now=int(time.time())),
                )
                self.assertEqual(current_response.status_code, 202)
                self.assertEqual(previous_response.status_code, 202)
                current_body = current_response.json()
                previous_body = previous_response.json()
                for key in ("status", "action", "message", "duplicate"):
                    self.assertEqual(current_body[key], previous_body[key])
                rendered = json.dumps(previous_body, ensure_ascii=False).casefold()
                self.assertNotIn("previous", rendered)
                self.assertNotIn("上一版本", rendered)
                self.assertNotIn(previous, rendered)
                self.assertNotIn(current, rendered)
            finally:
                service.shutdown(2.0)


if __name__ == "__main__":
    unittest.main()
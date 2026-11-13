from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from app.api.settings import WebSettings
from app.core.rules.common.models import ChangeStatus, FileGroup, ReportStatus, build_report
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import OpenApiMode
from app.webhook.app import create_webhook_app
from app.webhook.idempotency import IdempotencyRegistry, ReservationState
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import FrozenClock, WebhookASGIClient, make_headers, make_payload, no_network


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


class IdempotencyTest(unittest.TestCase):
    def test_duplicate_event(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(
                secret=secret,
                sync_mode=True,
                openapi_mode=OpenApiMode.MOCK,
                queue_capacity=2,
                worker_concurrency=1,
            )
            runner = _CountingRunner()
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=runner, adapter=adapter)
            app = create_webhook_app(config, service=service)
            payload = _payload(repo=root.name, event_id="evt-w39", changed_files=["main.py"])
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            client = WebhookASGIClient(app)
            try:
                first = client.post(config.path, content=raw, headers=_headers(secret, raw))
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.json()["status"], "completed")
                second = client.post(config.path, content=raw, headers=_headers(secret, raw))
                self.assertEqual(second.status_code, 202)
                body = second.json()
                self.assertEqual(body["status"], "duplicate")
                self.assertTrue(body["duplicate"])
                self.assertEqual(body["message"], "事件已处理，已跳过重复回评")
                self.assertEqual(runner.calls, 1)
                self.assertEqual(len(adapter.comments), 1)
            finally:
                service.shutdown(2.0)

    def test_concurrent_duplicate(self):
        clock = FrozenClock(0.0)
        registry = IdempotencyRegistry(ttl_seconds=3_600, capacity=100, clock=clock)
        barrier = threading.Barrier(8)
        results: list[ReservationState] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            result = registry.reserve("evt-w40", "f" * 64)
            with lock:
                results.append(result.state)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(results), 8)
        self.assertEqual(results.count(ReservationState.NEW), 1)
        self.assertEqual(results.count(ReservationState.DUPLICATE_PROCESSING), 7)
        self.assertEqual(registry.size, 1)

    def test_event_conflict(self):
        with tempfile.TemporaryDirectory() as temp, no_network():
            root = _root(temp)
            secret = os.urandom(16).hex()
            config = WebhookConfig(
                secret=secret,
                sync_mode=True,
                openapi_mode=OpenApiMode.MOCK,
                queue_capacity=2,
                worker_concurrency=1,
            )
            runner = _CountingRunner()
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _settings(root), runner=runner, adapter=adapter)
            app = create_webhook_app(config, service=service)
            first_payload = _payload(repo=root.name, event_id="evt-w41", changed_files=["main.py"])
            second_payload = _payload(repo=root.name, event_id="evt-w41", changed_files=["other.py"])
            raw_first = json.dumps(first_payload, ensure_ascii=False).encode("utf-8")
            raw_second = json.dumps(second_payload, ensure_ascii=False).encode("utf-8")
            client = WebhookASGIClient(app)
            try:
                first = client.post(config.path, content=raw_first, headers=_headers(secret, raw_first))
                self.assertEqual(first.status_code, 200)
                second = client.post(config.path, content=raw_second, headers=_headers(secret, raw_second))
                self.assertEqual(second.status_code, 409)
                self.assertEqual(second.json()["error"]["code"], "WEBHOOK_EVENT_CONFLICT")
                first_hash = hashlib.sha256(raw_first).hexdigest()
                reservation = service._registry.reserve("evt-w41", first_hash)
                self.assertIs(reservation.state, ReservationState.DUPLICATE_DONE)
                self.assertEqual(reservation.body_sha256, first_hash)
                self.assertEqual(service._registry.snapshot()["done"], 1)
            finally:
                service.shutdown(2.0)

    def test_idempotency_ttl_expired(self):
        clock = FrozenClock(1_000.0)
        registry = IdempotencyRegistry(ttl_seconds=60, capacity=100, clock=clock)
        first = registry.reserve("evt-w42", "a" * 64)
        self.assertIs(first.state, ReservationState.NEW)
        self.assertEqual(registry.size, 1)
        clock.advance(61)
        second = registry.reserve("evt-w42", "a" * 64)
        self.assertIs(second.state, ReservationState.NEW)
        self.assertEqual(second.attempt, 1)
        self.assertEqual(registry.evicted_count, 1)
        self.assertEqual(registry.size, 1)

    def test_idempotency_capacity_eviction(self):
        clock = FrozenClock(1_000.0)
        registry = IdempotencyRegistry(ttl_seconds=3_600, capacity=2, clock=clock)
        self.assertIs(registry.reserve("evt-a", "a" * 64).state, ReservationState.NEW)
        registry.complete("evt-a")
        self.assertIs(registry.reserve("evt-b", "b" * 64).state, ReservationState.NEW)
        self.assertIs(registry.reserve("evt-c", "c" * 64).state, ReservationState.NEW)
        self.assertEqual(registry.evicted_count, 1)
        self.assertEqual(registry.size, 2)
        self.assertIs(registry.reserve("evt-b", "b" * 64).state, ReservationState.DUPLICATE_PROCESSING)
        self.assertIs(registry.reserve("evt-d", "d" * 64).state, ReservationState.NEW)
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["size"], 3)
        self.assertEqual(snapshot["capacity"], 2)
        self.assertEqual(snapshot["evicted"], 1)
        self.assertEqual(snapshot["overflow"], 1)
        self.assertEqual(snapshot["processing"], 3)

    def test_retry_failed_disabled_by_default(self):
        clock = FrozenClock(1_000.0)
        registry = IdempotencyRegistry(ttl_seconds=3_600, capacity=100, clock=clock)
        self.assertIs(registry.reserve("evt-w44", "e" * 64).state, ReservationState.NEW)
        registry.fail("evt-w44", "WEBHOOK_ENGINE_ERROR")
        blocked = registry.reserve("evt-w44", "e" * 64)
        self.assertIs(blocked.state, ReservationState.DUPLICATE_FAILED)
        self.assertEqual(blocked.attempt, 1)
        self.assertEqual(blocked.error_code, "WEBHOOK_ENGINE_ERROR")
        allowed = registry.reserve("evt-w44", "e" * 64, allow_retry_failed=True)
        self.assertIs(allowed.state, ReservationState.RETRY_ALLOWED)
        self.assertEqual(allowed.attempt, 2)
        self.assertEqual(allowed.previous_state, "FAILED")


if __name__ == "__main__":
    unittest.main()
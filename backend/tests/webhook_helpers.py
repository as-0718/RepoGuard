from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import os
import socket
import time
from collections.abc import Iterator
from unittest.mock import patch

import httpx

from app.webhook.settings import WebhookConfig

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


def make_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    payload = timestamp.strip().encode("utf-8") + b"." + raw_body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def make_headers(
    secret: str,
    raw_body: bytes,
    event_type: str = "pr.created",
    event_id: str = "evt-001",
    *,
    timestamp: str | None = None,
    signature_prefix: str = "sha256=",
    delivery_id: str | None = None,
) -> dict[str, str]:
    defaults = WebhookConfig()
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    headers = {
        defaults.event_header: event_type,
        defaults.timestamp_header: stamp,
        defaults.signature_header: signature_prefix + make_signature(secret, stamp, raw_body),
    }
    if delivery_id is not None:
        headers[defaults.delivery_header] = delivery_id
    return headers


def make_payload(
    *,
    repo: str = "demo-repo",
    pr_number: int = 12,
    base_sha: str = "a" * 40,
    head_sha: str = "b" * 40,
    changed_files: list[str] | None = None,
    added_files: list[str] | None = None,
    modified_files: list[str] | None = None,
    removed_files: list[str] | None = None,
    action: str = "opened",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": "evt-001",
        "action": action,
        "repository": {"full_name": repo},
        "pull_request": {
            "number": pr_number,
            "base": {"sha": base_sha},
            "head": {"sha": head_sha},
        },
    }
    if changed_files is not None:
        payload["changed_files"] = list(changed_files)
    if added_files is not None:
        payload["added_files"] = list(added_files)
    if modified_files is not None:
        payload["modified_files"] = list(modified_files)
    if removed_files is not None:
        payload["removed_files"] = list(removed_files)
    return payload


class FrozenClock:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


class WebhookASGIClient:
    def __init__(self, app: object, timeout: float = 10.0) -> None:
        self.app = app
        self.timeout = timeout

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        async def run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=self.timeout) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run())

    def get(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def close(self) -> None:
        return None


@contextlib.contextmanager
def no_network() -> Iterator[None]:
    with patch("socket.socket", side_effect=AssertionError("network disabled")), patch(
        "socket.create_connection", side_effect=AssertionError("network disabled")
    ):
        yield
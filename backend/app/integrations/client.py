from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

from .models import OpenApiProfile

MAX_RESPONSE_BYTES: int = 65_536


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    elapsed_ms: float
    content_truncated: bool = False


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class HttpxHttpClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        verify_tls: bool = True,
        user_agent: str = "RepoGuard-Webhook/1.0",
    ) -> None:
        self._user_agent = user_agent
        self._client = httpx.Client(
            verify=verify_tls,
            follow_redirects=False,
            transport=transport,
            timeout=10.0,
        )
        self._closed = False

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        started = time.perf_counter()
        safe_headers = {
            key: value
            for key, value in headers.items()
            if key.casefold() in {"content-type", "user-agent", "accept", "authorization"}
            or key.casefold().startswith("x-")
        }
        safe_headers.setdefault("User-Agent", self._user_agent)
        response = self._client.request(
            method,
            url,
            headers=safe_headers,
            content=content,
            timeout=timeout,
        )
        truncated = len(response.content) > MAX_RESPONSE_BYTES
        body = response.content[:MAX_RESPONSE_BYTES] if truncated else response.content
        elapsed_ms = (time.perf_counter() - started) * 1000
        return HttpResponse(
            status_code=response.status_code,
            headers={key: value for key, value in response.headers.items()},
            content=body,
            elapsed_ms=elapsed_ms,
            content_truncated=truncated,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
        except Exception:
            pass


def build_http_client(
    profile: OpenApiProfile,
    *,
    transport: httpx.BaseTransport | None = None,
) -> HttpClient:
    return HttpxHttpClient(
        transport=transport,
        verify_tls=profile.verify_tls,
        user_agent=profile.user_agent,
    )
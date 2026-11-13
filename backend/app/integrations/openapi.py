from __future__ import annotations

import json
import os
import random
import time
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Protocol

import httpx

from .client import HttpClient, build_http_client
from .models import (
    AuthScheme,
    CommentPayloadLike,
    OpenApiConfigError,
    OpenApiMode,
    OpenApiProfile,
    PublishResult,
    host_is_forbidden_ip,
    is_loopback_host,
    read_dot_path,
    validate_profile,
)

DEFAULT_TOTAL_BUDGET_SECONDS: float = 30.0


class OpenApiAdapter(Protocol):
    def fetch_changed_files(
        self, repo: str, base_sha: str, head_sha: str
    ) -> tuple[str, ...] | None: ...

    def publish_comment(
        self, repo: str, pr_number: int, payload: CommentPayloadLike
    ) -> PublishResult: ...


class ConfigurableOpenApiAdapter:
    def __init__(
        self,
        profile: OpenApiProfile,
        *,
        client: HttpClient | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        env: Mapping[str, str] | None = None,
        token: str | None = None,
    ) -> None:
        missing = validate_profile(profile, OpenApiMode.LIVE)
        if missing:
            raise OpenApiConfigError(missing)
        self._profile = profile
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._client = client or build_http_client(profile)
        source = os.environ if env is None else env
        resolved = token if token is not None else source.get(profile.token_env, "")
        if profile.auth_scheme is not AuthScheme.NONE and not resolved.strip():
            raise OpenApiConfigError(("token_env",))
        self._token = resolved.strip()

    def __repr__(self) -> str:
        return "ConfigurableOpenApiAdapter(profile=<configured>, token=<redacted>)"

    def _url(self, template: str, repo: str, pr_number: int = 0) -> str:
        encoded_repo = urllib.parse.quote(repo, safe="/")
        rendered = template.replace("{repo}", encoded_repo).replace("{pr_number}", str(pr_number))
        return urllib.parse.urljoin(self._profile.base_url.rstrip("/") + "/", rendered)

    def _headers(self, content_type: str) -> tuple[dict[str, str], str | None]:
        headers = {"Content-Type": content_type, "Accept": "application/json", "User-Agent": self._profile.user_agent}
        if self._profile.auth_scheme is AuthScheme.BEARER:
            return headers, None
        if self._profile.auth_scheme is AuthScheme.HEADER:
            headers[self._profile.auth_header] = self._profile.auth_prefix + self._token
        return headers, None

    def _safe_url(self, url: str) -> bool:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return False
        if parsed.scheme not in ("https", "http"):
            return False
        if parsed.scheme == "http" and not is_loopback_host(parsed.hostname or ""):
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        host = (parsed.hostname or "").casefold()
        allowed = {item.casefold() for item in self._profile.allowed_hosts}
        if not host or host not in allowed or "*" in allowed:
            return False
        if host_is_forbidden_ip(host):
            return False
        return True

    def _auth_headers(self, content_type: str) -> dict[str, str]:
        headers = {
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": self._profile.user_agent,
        }
        if self._profile.auth_scheme is AuthScheme.BEARER:
            headers[self._profile.auth_header] = self._profile.auth_prefix + self._token
        elif self._profile.auth_scheme is AuthScheme.HEADER:
            headers[self._profile.auth_header] = self._profile.auth_prefix + self._token
        return headers

    def _render_body(self, payload: CommentPayloadLike) -> bytes | None:
        rendered = self._profile.body_template.replace(
            "{markdown}", json.dumps(payload.markdown, ensure_ascii=False)
        )
        try:
            parsed = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        return rendered.encode("utf-8")

    def _error_result(self, code: str, message: str, attempts: int = 1) -> PublishResult:
        return PublishResult(False, None, code, message, None, attempts, 0, attempts > 1)

    def publish_comment(
        self, repo: str, pr_number: int, payload: CommentPayloadLike
    ) -> PublishResult:
        started = self._clock()
        url = self._url(self._profile.comment_endpoint_template, repo, pr_number)
        if not self._safe_url(url):
            return self._error_result("OPENAPI_HOST_FORBIDDEN", "OpenAPI 主机不在允许范围内")
        body = self._render_body(payload)
        if body is None:
            return self._error_result("OPENAPI_NOT_CONFIGURED", "评论请求体模板不合法")
        headers = self._auth_headers("application/json")
        attempts = max(0, self._profile.max_retries) + 1
        retried = False
        last_error: tuple[str, str] | None = None
        for attempt in range(1, attempts + 1):
            remaining = DEFAULT_TOTAL_BUDGET_SECONDS - (self._clock() - started)
            if remaining <= 0:
                return self._error_result("OPENAPI_TIMEOUT", "OpenAPI 调用超时", attempt)
            timeout = min(self._profile.timeout_seconds, max(0.1, remaining))
            try:
                response = self._client.request(
                    "POST", url, headers=headers, content=body, timeout=timeout
                )
            except Exception as exc:
                code = "OPENAPI_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "OPENAPI_UNAVAILABLE"
                last_error = (code, "OpenAPI 暂时不可用")
                if attempt < attempts:
                    retried = True
                    delay = self._profile.backoff_base_seconds * (2 ** (attempt - 1))
                    self._sleeper(delay * (1 + random.uniform(-0.2, 0.2)))
                    continue
                break
            if response.status_code in self._profile.success_status_codes:
                try:
                    parsed = json.loads(response.content.decode("utf-8", errors="replace") or "{}")
                    comment_id = read_dot_path(parsed, self._profile.comment_id_response_path)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    comment_id = None
                return PublishResult(
                    True,
                    response.status_code,
                    None,
                    None,
                    str(comment_id) if comment_id is not None else None,
                    attempt,
                    int((self._clock() - started) * 1000),
                    retried,
                )
            status = response.status_code
            if status in (401, 403):
                return PublishResult(False, status, "OPENAPI_AUTH_FAILED", "OpenAPI 认证失败", None, attempt, int((self._clock() - started) * 1000), retried)
            if status == 404:
                return PublishResult(False, status, "OPENAPI_NOT_FOUND", "OpenAPI 资源不存在", None, attempt, int((self._clock() - started) * 1000), retried)
            if 300 <= status < 400:
                return PublishResult(False, status, "OPENAPI_REDIRECT_FORBIDDEN", "OpenAPI 不允许重定向", None, attempt, int((self._clock() - started) * 1000), retried)
            if status in (400, 413):
                return PublishResult(False, status, "OPENAPI_COMMENT_TOO_LONG", "评论内容被平台拒绝", None, attempt, int((self._clock() - started) * 1000), retried)
            if status == 429 or status >= 500:
                last_error = ("OPENAPI_UNAVAILABLE", "OpenAPI 暂时不可用")
                if attempt < attempts:
                    retried = True
                    delay = self._profile.backoff_base_seconds * (2 ** (attempt - 1))
                    self._sleeper(delay * (1 + random.uniform(-0.2, 0.2)))
                    continue
                break
            return PublishResult(False, status, "OPENAPI_UNAVAILABLE", "OpenAPI 返回未预期状态", None, attempt, int((self._clock() - started) * 1000), retried)
        code, message = last_error or ("OPENAPI_UNAVAILABLE", "OpenAPI 暂时不可用")
        return PublishResult(False, None, code, message, None, attempts, int((self._clock() - started) * 1000), retried)

    def fetch_changed_files(
        self, repo: str, base_sha: str, head_sha: str
    ) -> tuple[str, ...] | None:
        template = self._profile.changed_files_endpoint_template
        if not template or not base_sha or not head_sha:
            return None
        url = self._url(template, repo)
        url = url.replace("{base_sha}", urllib.parse.quote(base_sha, safe=""))
        url = url.replace("{head_sha}", urllib.parse.quote(head_sha, safe=""))
        if not self._safe_url(url):
            return None
        headers = self._auth_headers("application/json")
        try:
            response = self._client.request(
                "GET", url, headers=headers, content=None, timeout=min(self._profile.timeout_seconds, 10.0)
            )
        except Exception:
            return None
        if response.status_code not in self._profile.success_status_codes or response.content_truncated:
            return None
        try:
            payload = json.loads(response.content.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        value = read_dot_path(payload, self._profile.changed_files_response_path)
        if not isinstance(value, (list, tuple)):
            return None
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            result.append(item)
        return tuple(result)

    def close(self) -> None:
        closer = getattr(self._client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
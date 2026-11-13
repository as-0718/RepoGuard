from __future__ import annotations

import ipaddress
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol


class OpenApiError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.detail = detail


class OpenApiConfigError(OpenApiError):
    def __init__(
        self,
        missing_fields: tuple[str, ...],
        code: str = "OPENAPI_NOT_CONFIGURED",
        status_code: int = 503,
        message: str = "OpenAPI 配置不完整",
        detail: str | None = None,
    ) -> None:
        super().__init__(code, status_code, message, detail)
        self.missing_fields = tuple(missing_fields)


class OpenApiMode(Enum):
    DISABLED = "disabled"
    MOCK = "mock"
    LIVE = "live"


class AuthScheme(Enum):
    BEARER = "bearer"
    HEADER = "header"
    NONE = "none"


class CommentPayloadLike(Protocol):
    event_id: str
    repo_label: str
    pull_request_number: int
    markdown: str
    char_count: int
    byte_count: int
    truncated: bool
    omitted_must_fix: int
    omitted_suggestions: int
    marker: str
    check_status: str
    must_fix_count: int
    suggestion_count: int
    issue_count: int
    skipped_file_count: int
    degraded_module_count: int


@dataclass(frozen=True, slots=True)
class OpenApiProfile:
    base_url: str = ""
    comment_endpoint_template: str = ""
    changed_files_endpoint_template: str | None = None
    auth_scheme: AuthScheme = AuthScheme.BEARER
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    token_env: str = "REPOGUARD_OPENAPI_TOKEN"
    body_template: str = ""
    comment_marker_template: str = "<!-- repoguard:event:{event_id} -->"
    changed_files_response_path: str = "data.changed_files"
    comment_id_response_path: str = "data.id"
    success_status_codes: tuple[int, ...] = (200, 201)
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.5
    allowed_hosts: tuple[str, ...] = ()
    verify_tls: bool = True
    follow_redirects: bool = False
    user_agent: str = "RepoGuard-Webhook/1.0"


@dataclass(frozen=True, slots=True)
class PublishResult:
    success: bool
    status_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    comment_id: str | None = None
    attempts: int = 1
    duration_ms: int = 0
    retried: bool = False


def is_loopback_host(host: str) -> bool:
    value = host.strip().casefold()
    return value in {"127.0.0.1", "::1", "localhost"}


def _host_from_url(value: str) -> str:
    try:
        return urllib.parse.urlsplit(value).hostname or ""
    except ValueError:
        return ""


def _validate_url(profile: OpenApiProfile) -> list[str]:
    missing: list[str] = []
    if not profile.base_url:
        missing.append("base_url")
        return missing
    try:
        parsed = urllib.parse.urlsplit(profile.base_url)
    except ValueError:
        return ["base_url"]
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        missing.append("base_url")
    elif parsed.scheme == "http" and not is_loopback_host(parsed.hostname):
        missing.append("base_url")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        missing.append("base_url")
    if profile.verify_tls is False and not is_loopback_host(parsed.hostname):
        missing.append("verify_tls")
    return missing


def validate_profile(profile: OpenApiProfile | None, mode: OpenApiMode) -> tuple[str, ...]:
    if mode in (OpenApiMode.DISABLED, OpenApiMode.MOCK):
        return ()
    if profile is None:
        return (
            "base_url",
            "comment_endpoint_template",
            "body_template",
            "allowed_hosts",
            "token_env",
        )
    missing: list[str] = list(_validate_url(profile))
    if not profile.comment_endpoint_template:
        missing.append("comment_endpoint_template")
    elif "{repo}" not in profile.comment_endpoint_template or "{pr_number}" not in profile.comment_endpoint_template:
        missing.append("comment_endpoint_template")
    if not profile.body_template:
        missing.append("body_template")
    elif "{markdown}" not in profile.body_template:
        missing.append("body_template")
    else:
        sample = profile.body_template.replace("{markdown}", '""')
        import json

        try:
            parsed_body = json.loads(sample)
            if not isinstance(parsed_body, dict):
                missing.append("body_template")
        except (json.JSONDecodeError, ValueError):
            missing.append("body_template")
    if profile.changed_files_endpoint_template:
        for item in ("{repo}", "{base_sha}", "{head_sha}"):
            if item not in profile.changed_files_endpoint_template:
                missing.append("changed_files_endpoint_template")
                break
    host = _host_from_url(profile.base_url)
    allowed = tuple(item.strip().casefold() for item in profile.allowed_hosts if item.strip())
    if not allowed or "*" in allowed or host.casefold() not in allowed:
        missing.append("allowed_hosts")
    if profile.follow_redirects:
        missing.append("follow_redirects")
    if not profile.success_status_codes:
        missing.append("success_status_codes")
    if not (1.0 <= profile.timeout_seconds <= 60.0):
        missing.append("timeout_seconds")
    if not (0 <= profile.max_retries <= 5):
        missing.append("max_retries")
    if not (0.1 <= profile.backoff_base_seconds <= 5.0):
        missing.append("backoff_base_seconds")
    if profile.auth_scheme is not AuthScheme.NONE and not profile.token_env:
        missing.append("token_env")
    if not profile.auth_header:
        missing.append("auth_header")
    if "{event_id}" not in profile.comment_marker_template:
        missing.append("comment_marker_template")
    if not profile.changed_files_response_path:
        missing.append("changed_files_response_path")
    if not profile.comment_id_response_path:
        missing.append("comment_id_response_path")
    if not profile.user_agent or "@" in profile.user_agent:
        missing.append("user_agent")
    return tuple(dict.fromkeys(missing))


def read_dot_path(payload: object, path: str) -> object | None:
    current = payload
    for segment in path.split("."):
        if not segment:
            return None
        if isinstance(current, Mapping):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, (list, tuple)):
            try:
                index = int(segment)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def host_is_forbidden_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return False
    return bool(
        address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or str(address) == "169.254.169.254"
    )
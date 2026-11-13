from __future__ import annotations

import json
import logging
import os
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Callable

from ..integrations.models import AuthScheme, OpenApiMode, OpenApiProfile
from .models import WebhookError

LOGGER = logging.getLogger("repoguard.webhook.settings")
DEFAULT_FIELD_MAP: Mapping[str, tuple[str, ...]] = types.MappingProxyType(
    {
        "event_id": ("event_id", "id", "delivery_id"),
        "event_type": ("event_type", "object_kind", "event_name"),
        "repository": (
            "repository.full_name",
            "repository.name",
            "repo",
            "project.path_with_namespace",
        ),
        "pull_request_number": ("pull_request.number", "merge_request.iid", "number"),
        "base_sha": ("pull_request.base.sha", "base_sha", "object_attributes.target.sha"),
        "head_sha": ("pull_request.head.sha", "head_sha", "object_attributes.last_commit.id"),
        "action": ("action", "object_attributes.action", "pull_request.action"),
        "changed_files": ("changed_files",),
        "added_files": ("added_files",),
        "modified_files": ("modified_files",),
        "removed_files": ("removed_files",),
    }
)
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/-]*$")


class ConfigError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8010
    path: str = "/webhook"
    secret: str = ""
    secret_previous: str = ""
    signature_header: str = "X-RepoGuard-Signature"
    signature_prefix: str = "sha256="
    timestamp_header: str = "X-RepoGuard-Timestamp"
    event_header: str = "X-RepoGuard-Event"
    delivery_header: str = "X-RepoGuard-Delivery"
    event_types: tuple[str, ...] = ("pr.created", "pr.updated", "mr.created", "mr.updated")
    field_map: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: types.MappingProxyType(dict(DEFAULT_FIELD_MAP)))
    replay_window_seconds: int = 300
    max_body_bytes: int = 1_048_576
    max_changed_files: int = 5_000
    idempotency_ttl_seconds: int = 86_400
    idempotency_capacity: int = 10_000
    queue_capacity: int = 100
    worker_concurrency: int = 2
    task_timeout_seconds: float = 120.0
    sync_mode: bool = False
    openapi_mode: OpenApiMode = OpenApiMode.DISABLED
    openapi_profile: OpenApiProfile | None = None
    repo_map: Mapping[str, str] = field(default_factory=lambda: types.MappingProxyType({}))
    notify_on_failure: bool = True
    notify_on_clean: bool = True
    max_comment_chars: int = 60_000
    record_buffer_size: int = 500
    log_level: str = "INFO"
    idempotency_retry_failed: bool = False
    stop_timeout_seconds: float = 10.0
    duplicate_comment_check: bool = False
    event_kind_map: Mapping[str, str] = field(default_factory=lambda: types.MappingProxyType({}))


def default_config() -> WebhookConfig:
    return WebhookConfig()


def _clamp_int(value: object, default: int, low: int, high: int, name: str) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(str(value))
    except (TypeError, ValueError):
        LOGGER.warning("配置项 %s 非法，已使用默认值", name)
        return default
    if number < low or number > high:
        LOGGER.warning("配置项 %s 超出范围，已使用默认值", name)
        return default
    return number


def _clamp_float(value: object, default: float, low: float, high: float, name: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(str(value))
    except (TypeError, ValueError):
        LOGGER.warning("配置项 %s 非法，已使用默认值", name)
        return default
    if number < low or number > high:
        LOGGER.warning("配置项 %s 超出范围，已使用默认值", name)
        return default
    return number


def _bool(value: object, default: bool, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    LOGGER.warning("配置项 %s 不是合法布尔值，已使用默认值", name)
    return default


def normalize_config(config: WebhookConfig) -> WebhookConfig:
    defaults = WebhookConfig()
    host = config.host.strip() if isinstance(config.host, str) else defaults.host
    if not host or any(ord(char) < 32 for char in host):
        host = defaults.host
    path = validate_webhook_path(config.path)
    if path != config.path:
        LOGGER.warning("Webhook 路径非法，已回退为 %s", path)
    mode = config.openapi_mode if isinstance(config.openapi_mode, OpenApiMode) else OpenApiMode.DISABLED
    if not isinstance(config.openapi_mode, OpenApiMode):
        LOGGER.warning("OpenAPI 模式非法，已回退为 disabled")
    log_level = config.log_level.upper() if isinstance(config.log_level, str) else defaults.log_level
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        log_level = defaults.log_level
    return replace(
        config,
        host=host,
        port=_clamp_int(config.port, defaults.port, 1, 65535, "port"),
        path=path,
        replay_window_seconds=_clamp_int(config.replay_window_seconds, defaults.replay_window_seconds, 30, 900, "replay_window_seconds"),
        max_body_bytes=_clamp_int(config.max_body_bytes, defaults.max_body_bytes, 65_536, 8_388_608, "max_body_bytes"),
        max_changed_files=_clamp_int(config.max_changed_files, defaults.max_changed_files, 1, 20_000, "max_changed_files"),
        idempotency_ttl_seconds=_clamp_int(config.idempotency_ttl_seconds, defaults.idempotency_ttl_seconds, 60, 604_800, "idempotency_ttl_seconds"),
        idempotency_capacity=_clamp_int(config.idempotency_capacity, defaults.idempotency_capacity, 100, 100_000, "idempotency_capacity"),
        queue_capacity=_clamp_int(config.queue_capacity, defaults.queue_capacity, 1, 1_000, "queue_capacity"),
        worker_concurrency=_clamp_int(config.worker_concurrency, defaults.worker_concurrency, 1, 8, "worker_concurrency"),
        task_timeout_seconds=_clamp_float(config.task_timeout_seconds, defaults.task_timeout_seconds, 30.0, 300.0, "task_timeout_seconds"),
        stop_timeout_seconds=_clamp_float(config.stop_timeout_seconds, defaults.stop_timeout_seconds, 1.0, 60.0, "stop_timeout_seconds"),
        max_comment_chars=_clamp_int(config.max_comment_chars, defaults.max_comment_chars, 1_000, 100_000, "max_comment_chars"),
        record_buffer_size=_clamp_int(config.record_buffer_size, defaults.record_buffer_size, 10, 10_000, "record_buffer_size"),
        openapi_mode=mode,
        log_level=log_level,
        secret="" if _has_control(config.secret) else config.secret,
        secret_previous="" if _has_control(config.secret_previous) else config.secret_previous,
    )


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def validate_webhook_path(path: str) -> str:
    if not isinstance(path, str) or not (1 <= len(path) <= 64):
        return "/webhook"
    if not path.startswith("/") or path.startswith("//") or ".." in path.split("/"):
        return "/webhook"
    if not _PATH_RE.match(path) or _has_control(path):
        return "/webhook"
    return path


def _read_env(env: Mapping[str, str], name: str, default: str) -> str:
    return env.get(name, default)


def _json_mapping(raw: str, name: str) -> Mapping[str, str]:
    if not raw:
        return types.MappingProxyType({})
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        LOGGER.warning("配置项 %s 不是合法 JSON，已使用空映射", name)
        return types.MappingProxyType({})
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        LOGGER.warning("配置项 %s 结构非法，已使用空映射", name)
        return types.MappingProxyType({})
    return types.MappingProxyType(value)


def load_webhook_config(env: Mapping[str, str] | None = None) -> WebhookConfig:
    source = os.environ if env is None else env
    defaults = WebhookConfig()
    event_types_raw = source.get("REPOGUARD_WEBHOOK_EVENT_TYPES", "")
    event_types = tuple(item.strip() for item in event_types_raw.split(",") if item.strip()) or defaults.event_types
    auth_scheme_raw = source.get("REPOGUARD_OPENAPI_AUTH_SCHEME", "bearer").casefold()
    auth_scheme = {"bearer": AuthScheme.BEARER, "header": AuthScheme.HEADER, "none": AuthScheme.NONE}.get(auth_scheme_raw, AuthScheme.BEARER)
    mode_raw = source.get("REPOGUARD_OPENAPI_MODE", "disabled").casefold()
    mode = {"disabled": OpenApiMode.DISABLED, "mock": OpenApiMode.MOCK, "live": OpenApiMode.LIVE}.get(mode_raw, OpenApiMode.DISABLED)
    profile = None
    if mode is not OpenApiMode.DISABLED:
        profile = OpenApiProfile(
            base_url=source.get("REPOGUARD_OPENAPI_BASE_URL", ""),
            comment_endpoint_template=source.get("REPOGUARD_OPENAPI_COMMENT_ENDPOINT_TEMPLATE", ""),
            changed_files_endpoint_template=source.get("REPOGUARD_OPENAPI_CHANGED_FILES_ENDPOINT_TEMPLATE") or None,
            auth_scheme=auth_scheme,
            auth_header=source.get("REPOGUARD_OPENAPI_AUTH_HEADER", "Authorization"),
            auth_prefix=source.get("REPOGUARD_OPENAPI_AUTH_PREFIX", "Bearer "),
            token_env=source.get("REPOGUARD_OPENAPI_TOKEN_ENV", "REPOGUARD_OPENAPI_TOKEN"),
            body_template=source.get("REPOGUARD_OPENAPI_BODY_TEMPLATE", ""),
            comment_marker_template=source.get("REPOGUARD_OPENAPI_COMMENT_MARKER_TEMPLATE", "<!-- repoguard:event:{event_id} -->"),
            changed_files_response_path=source.get("REPOGUARD_OPENAPI_CHANGED_FILES_RESPONSE_PATH", "data.changed_files"),
            comment_id_response_path=source.get("REPOGUARD_OPENAPI_COMMENT_ID_RESPONSE_PATH", "data.id"),
            success_status_codes=_parse_status_codes(source.get("REPOGUARD_OPENAPI_SUCCESS_STATUS_CODES", "200,201")),
            timeout_seconds=_clamp_float(source.get("REPOGUARD_OPENAPI_TIMEOUT_SECONDS", 10.0), 10.0, 1.0, 60.0, "openapi_timeout"),
            max_retries=_clamp_int(source.get("REPOGUARD_OPENAPI_MAX_RETRIES", 2), 2, 0, 5, "openapi_max_retries"),
            backoff_base_seconds=_clamp_float(source.get("REPOGUARD_OPENAPI_BACKOFF_BASE_SECONDS", 0.5), 0.5, 0.1, 5.0, "openapi_backoff"),
            allowed_hosts=tuple(item.strip() for item in source.get("REPOGUARD_OPENAPI_ALLOWED_HOSTS", "").split(",") if item.strip()),
            verify_tls=_bool(source.get("REPOGUARD_OPENAPI_VERIFY_TLS", "true"), True, "verify_tls"),
            follow_redirects=_bool(source.get("REPOGUARD_OPENAPI_FOLLOW_REDIRECTS", "false"), False, "follow_redirects"),
            user_agent=source.get("REPOGUARD_OPENAPI_USER_AGENT", "RepoGuard-Webhook/1.0"),
        )
    config = WebhookConfig(
        enabled=_bool(source.get("REPOGUARD_WEBHOOK_ENABLED", "true"), True, "enabled"),
        host=source.get("REPOGUARD_WEBHOOK_HOST", defaults.host),
        port=_clamp_int(source.get("REPOGUARD_WEBHOOK_PORT", defaults.port), defaults.port, 1, 65535, "port"),
        path=source.get("REPOGUARD_WEBHOOK_PATH", defaults.path),
        secret=source.get("REPOGUARD_WEBHOOK_SECRET", ""),
        secret_previous=source.get("REPOGUARD_WEBHOOK_SECRET_PREVIOUS", ""),
        signature_header=source.get("REPOGUARD_WEBHOOK_SIGNATURE_HEADER", defaults.signature_header),
        signature_prefix=source.get("REPOGUARD_WEBHOOK_SIGNATURE_PREFIX", defaults.signature_prefix),
        timestamp_header=source.get("REPOGUARD_WEBHOOK_TIMESTAMP_HEADER", defaults.timestamp_header),
        event_header=source.get("REPOGUARD_WEBHOOK_EVENT_HEADER", defaults.event_header),
        delivery_header=source.get("REPOGUARD_WEBHOOK_DELIVERY_HEADER", defaults.delivery_header),
        event_types=event_types,
        field_map=_json_sequence_map(source.get("REPOGUARD_WEBHOOK_FIELD_MAP", "")),
        replay_window_seconds=_clamp_int(source.get("REPOGUARD_WEBHOOK_REPLAY_WINDOW_SECONDS", defaults.replay_window_seconds), defaults.replay_window_seconds, 30, 900, "replay_window"),
        max_body_bytes=_clamp_int(source.get("REPOGUARD_WEBHOOK_MAX_BODY_BYTES", defaults.max_body_bytes), defaults.max_body_bytes, 65_536, 8_388_608, "max_body_bytes"),
        max_changed_files=_clamp_int(source.get("REPOGUARD_WEBHOOK_MAX_CHANGED_FILES", defaults.max_changed_files), defaults.max_changed_files, 1, 20_000, "max_changed_files"),
        idempotency_ttl_seconds=_clamp_int(source.get("REPOGUARD_WEBHOOK_IDEMPOTENCY_TTL_SECONDS", defaults.idempotency_ttl_seconds), defaults.idempotency_ttl_seconds, 60, 604_800, "idempotency_ttl"),
        idempotency_capacity=_clamp_int(source.get("REPOGUARD_WEBHOOK_IDEMPOTENCY_CAPACITY", defaults.idempotency_capacity), defaults.idempotency_capacity, 100, 100_000, "idempotency_capacity"),
        queue_capacity=_clamp_int(source.get("REPOGUARD_WEBHOOK_QUEUE_CAPACITY", defaults.queue_capacity), defaults.queue_capacity, 1, 1_000, "queue_capacity"),
        worker_concurrency=_clamp_int(source.get("REPOGUARD_WEBHOOK_WORKER_CONCURRENCY", defaults.worker_concurrency), defaults.worker_concurrency, 1, 8, "worker_concurrency"),
        task_timeout_seconds=_clamp_float(source.get("REPOGUARD_WEBHOOK_TASK_TIMEOUT_SECONDS", defaults.task_timeout_seconds), defaults.task_timeout_seconds, 30.0, 300.0, "task_timeout"),
        sync_mode=_bool(source.get("REPOGUARD_WEBHOOK_SYNC_MODE", "false"), False, "sync_mode"),
        openapi_mode=mode,
        openapi_profile=profile,
        repo_map=_json_mapping(source.get("REPOGUARD_WEBHOOK_REPO_MAP", ""), "repo_map"),
        notify_on_failure=_bool(source.get("REPOGUARD_WEBHOOK_NOTIFY_ON_FAILURE", "true"), True, "notify_on_failure"),
        notify_on_clean=_bool(source.get("REPOGUARD_WEBHOOK_NOTIFY_ON_CLEAN", "true"), True, "notify_on_clean"),
        max_comment_chars=_clamp_int(source.get("REPOGUARD_WEBHOOK_MAX_COMMENT_CHARS", defaults.max_comment_chars), defaults.max_comment_chars, 1_000, 100_000, "max_comment_chars"),
        record_buffer_size=_clamp_int(source.get("REPOGUARD_WEBHOOK_RECORD_BUFFER_SIZE", defaults.record_buffer_size), defaults.record_buffer_size, 10, 10_000, "record_buffer_size"),
        log_level=source.get("REPOGUARD_WEBHOOK_LOG_LEVEL", defaults.log_level),
        idempotency_retry_failed=_bool(source.get("REPOGUARD_WEBHOOK_IDEMPOTENCY_RETRY_FAILED", "false"), False, "idempotency_retry_failed"),
        stop_timeout_seconds=_clamp_float(source.get("REPOGUARD_WEBHOOK_STOP_TIMEOUT_SECONDS", 10.0), 10.0, 1.0, 60.0, "stop_timeout"),
        duplicate_comment_check=_bool(source.get("REPOGUARD_WEBHOOK_DUPLICATE_COMMENT_CHECK", "false"), False, "duplicate_comment_check"),
        event_kind_map=_json_mapping(source.get("REPOGUARD_WEBHOOK_EVENT_KIND_MAP", ""), "event_kind_map"),
    )
    return normalize_config(config)


def _parse_status_codes(raw: str) -> tuple[int, ...]:
    result: list[int] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            code = int(text)
        except ValueError:
            continue
        if 100 <= code <= 599:
            result.append(code)
    return tuple(result) or (200, 201)


def _json_sequence_map(raw: str) -> Mapping[str, tuple[str, ...]]:
    if not raw:
        return types.MappingProxyType(dict(DEFAULT_FIELD_MAP))
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        LOGGER.warning("field_map 不是合法 JSON，已使用默认值")
        return types.MappingProxyType(dict(DEFAULT_FIELD_MAP))
    if not isinstance(value, dict):
        return types.MappingProxyType(dict(DEFAULT_FIELD_MAP))
    result: dict[str, tuple[str, ...]] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, list) and all(isinstance(path, str) for path in item):
            result[key] = tuple(item)
    return types.MappingProxyType(result or dict(DEFAULT_FIELD_MAP))


def load_openapi_profile(env: Mapping[str, str] | None = None) -> OpenApiProfile | None:
    config = load_webhook_config(env)
    return config.openapi_profile


def config_summary(config: WebhookConfig) -> dict[str, object]:
    return {
        "enabled": config.enabled,
        "host": config.host,
        "port": config.port,
        "path": config.path,
        "openapi_mode": config.openapi_mode.value,
        "replay_window": config.replay_window_seconds,
        "queue_capacity": config.queue_capacity,
        "worker_concurrency": config.worker_concurrency,
        "max_body_bytes": config.max_body_bytes,
        "secret_configured": bool(config.secret.strip()),
        "token_configured": bool(
            config.openapi_profile
            and config.openapi_profile.auth_scheme is not AuthScheme.NONE
            and os.environ.get(config.openapi_profile.token_env, "").strip()
        ),
    }
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import (
    ChangedFilesSource,
    EventKind,
    NormalizedEvent,
    WebhookError,
    WebhookEvent,
    utc_now,
)
from .settings import WebhookConfig

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_ALLOWED_ACTIONS = {
    "opened",
    "created",
    "updated",
    "edited",
    "synchronize",
    "synchronized",
    "reopened",
    "ready_for_review",
}


class EventParseError(WebhookError):
    pass


def decode_json_object(raw_body: bytes) -> Mapping[str, object]:
    if not raw_body:
        raise EventParseError("WEBHOOK_INVALID_JSON", 400, "事件内容为空")
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EventParseError("WEBHOOK_INVALID_JSON", 400, "事件内容不是合法 UTF-8") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EventParseError("WEBHOOK_INVALID_JSON", 400, "事件内容不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise EventParseError("WEBHOOK_INVALID_JSON", 400, "事件内容顶层必须是 JSON 对象")
    return value


def read_field(payload: Mapping[str, object], paths: Sequence[str]) -> object | None:
    for path in paths:
        current: object = payload
        found = True
        for segment in path.split("."):
            if isinstance(current, Mapping):
                if segment not in current:
                    found = False
                    break
                current = current[segment]
            elif isinstance(current, (list, tuple)):
                try:
                    index = int(segment)
                except ValueError:
                    found = False
                    break
                if index < 0 or index >= len(current):
                    found = False
                    break
                current = current[index]
            else:
                found = False
                break
        if found and current is not None and not isinstance(current, (float, bool)):
            if isinstance(current, str) and not current.strip():
                continue
            return current
    return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value.strip() or None
    return None


def detect_event_type(
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    config: WebhookConfig,
) -> str:
    header_value = _header(headers, config.event_header)
    if header_value:
        return header_value
    value = read_field(payload, config.field_map.get("event_type", ()))
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件类型缺失或不合法")


def classify_event_kind(event_type: str, config: WebhookConfig) -> EventKind | None:
    mapped = config.event_kind_map.get(event_type.casefold())
    if mapped is not None:
        if mapped.casefold() == "created":
            return EventKind.CREATED
        if mapped.casefold() == "updated":
            return EventKind.UPDATED
        return None
    suffix = re.split(r"[./]", event_type.strip().casefold())[-1]
    if suffix in {"created", "opened", "reopened"}:
        return EventKind.CREATED
    if suffix in {"updated", "edited", "synchronize", "synchronized"}:
        return EventKind.UPDATED
    return None


def is_action_allowed(action: str | None, kind: EventKind) -> bool:
    del kind
    if action is None or not action.strip():
        return True
    return action.strip().casefold() in _ALLOWED_ACTIONS


def content_hash(
    event_type: str,
    repository_identifier: str,
    pull_request_number: int,
    base_sha: str | None,
    head_sha: str | None,
    raw_body: bytes,
) -> str:
    parts = (
        event_type,
        repository_identifier,
        str(pull_request_number),
        base_sha or "",
        head_sha or "",
    )
    payload = "\n".join(parts).encode("utf-8") + b"\n" + raw_body
    return hashlib.sha256(payload).hexdigest()


def compute_event_id(
    payload: Mapping[str, object],
    headers: Mapping[str, str],
    body_sha256: str,
    config: WebhookConfig,
) -> tuple[str, str]:
    value = read_field(payload, config.field_map.get("event_id", ()))
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value).strip()
        if 1 <= len(text) <= 200:
            return text, "payload"
    delivery = _header(headers, config.delivery_header)
    if delivery and 1 <= len(delivery) <= 200:
        return delivery, "delivery_header"
    return body_sha256, "content_hash"


def _filter_headers(headers: Mapping[str, str], config: WebhookConfig) -> Mapping[str, str]:
    allowed = {
        config.signature_header.casefold(),
        config.timestamp_header.casefold(),
        config.event_header.casefold(),
        config.delivery_header.casefold(),
    }
    result: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.casefold()
        if lowered in {"authorization", "cookie", "set-cookie"}:
            continue
        if lowered in allowed:
            result[key] = value
    return result


def _required_string(payload: Mapping[str, object], config: WebhookConfig, key: str) -> str:
    value = read_field(payload, config.field_map.get(key, ()))
    if not isinstance(value, str) or not value.strip():
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", f"字段：{key}")
    return value.strip()


def _required_pr(payload: Mapping[str, object], config: WebhookConfig) -> int:
    value = read_field(payload, config.field_map.get("pull_request_number", ()))
    if isinstance(value, bool):
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", "字段：pull_request_number")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", "字段：pull_request_number")
    if number <= 0:
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", "字段：pull_request_number")
    return number


def _optional_sha(payload: Mapping[str, object], config: WebhookConfig, key: str) -> str | None:
    value = read_field(payload, config.field_map.get(key, ()))
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA_RE.match(value.strip()):
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", f"字段：{key}")
    return value.strip().lower()


def parse_event(
    raw_body: bytes,
    headers: Mapping[str, str],
    config: WebhookConfig,
) -> WebhookEvent:
    body_hash = hashlib.sha256(raw_body).hexdigest()
    payload = decode_json_object(raw_body)
    event_type = detect_event_type(headers, payload, config)
    repository = _required_string(payload, config, "repository")
    pull_request_number = _required_pr(payload, config)
    base_sha = _optional_sha(payload, config, "base_sha")
    head_sha = _optional_sha(payload, config, "head_sha")
    action_value = read_field(payload, config.field_map.get("action", ()))
    action = action_value.strip() if isinstance(action_value, str) and action_value.strip() else None
    if action is not None and len(action) > 50:
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "事件字段不合法", "字段：action")
    event_id, source = compute_event_id(payload, headers, body_hash, config)
    return WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        action=action,
        repository_identifier=repository,
        pull_request_number=pull_request_number,
        base_sha=base_sha,
        head_sha=head_sha,
        raw_payload=payload,
        headers=_filter_headers(headers, config),
        body_sha256=body_hash,
        received_at=utc_now(),
        event_id_source=source,
    )


def normalize_changed_path(raw: str) -> tuple[str | None, str | None]:
    text = raw.strip()
    if not text:
        return None, "空路径"
    if text.startswith(("//", "\\\\", "\\\\?\\", "\\\\.\\")):
        return None, "UNC 或设备路径"
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = re.sub(r"/{2,}", "/", text)
    text = text.rstrip("/")
    if text.startswith("/") or _DRIVE_RE.match(text):
        return None, "绝对路径"
    segments = text.split("/")
    if any(segment == ".." for segment in segments):
        return None, "路径越界"
    if any(not segment or segment == "." for segment in segments):
        return None, "路径段非法"
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None, "含控制字符"
    if len(text) > 512:
        return None, "路径过长"
    return text, None


def _normalize_paths(raw_paths: Sequence[object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    valid: list[str] = []
    illegal: list[str] = []
    seen: set[str] = set()
    for item in raw_paths:
        if not isinstance(item, str):
            continue
        normalized, error = normalize_changed_path(item)
        if normalized is None:
            illegal.append(item[:200])
            continue
        if normalized not in seen:
            seen.add(normalized)
            valid.append(normalized)
    return tuple(valid), tuple(illegal)


def extract_changed_files_with_statuses(
    payload: Mapping[str, object], config: WebhookConfig
) -> tuple[tuple[str, ...], ChangedFilesSource, Mapping[str, str], tuple[str, ...]]:
    changed_value = read_field(payload, config.field_map.get("changed_files", ()))
    if isinstance(changed_value, (list, tuple)) and changed_value:
        valid, illegal = _normalize_paths(changed_value)
        statuses = {path: "M" for path in valid}
        return valid, ChangedFilesSource.PAYLOAD, statuses, illegal
    lists: list[tuple[str, Sequence[object]]] = []
    for key, status in (("added_files", "A"), ("modified_files", "M"), ("removed_files", "D")):
        value = read_field(payload, config.field_map.get(key, ()))
        if isinstance(value, (list, tuple)) and value:
            lists.append((status, value))
    if lists:
        ordered: list[str] = []
        statuses_map: dict[str, str] = {}
        illegal_all: list[str] = []
        for status, values in lists:
            valid, illegal = _normalize_paths(values)
            illegal_all.extend(illegal)
            for path in valid:
                if path not in statuses_map:
                    statuses_map[path] = status
                    ordered.append(path)
        return tuple(ordered), ChangedFilesSource.PAYLOAD_LISTS, statuses_map, tuple(illegal_all)

    if should_fetch_via_openapi_values(payload, config):
        return (), ChangedFilesSource.OPENAPI, {}, ()
    return (), ChangedFilesSource.NONE, {}, ()


def extract_changed_files(
    payload: Mapping[str, object], config: WebhookConfig
) -> tuple[tuple[str, ...], ChangedFilesSource]:
    paths, source, _, _ = extract_changed_files_with_statuses(payload, config)
    return paths, source


def should_fetch_via_openapi_values(payload: Mapping[str, object], config: WebhookConfig) -> bool:
    profile = config.openapi_profile
    if profile is None or not profile.changed_files_endpoint_template:
        return False
    if config.openapi_mode.value == "disabled":
        return False
    base_sha = read_field(payload, config.field_map.get("base_sha", ()))
    head_sha = read_field(payload, config.field_map.get("head_sha", ()))
    return bool(isinstance(base_sha, str) and base_sha.strip() and isinstance(head_sha, str) and head_sha.strip())


def should_fetch_via_openapi(normalized: NormalizedEvent, config: WebhookConfig) -> bool:
    profile = config.openapi_profile
    return bool(
        normalized.changed_files_source is ChangedFilesSource.OPENAPI
        or (
            profile is not None
            and profile.changed_files_endpoint_template
            and normalized.base_sha
            and normalized.head_sha
            and config.openapi_mode.value != "disabled"
        )
    )


def normalize_event(event: WebhookEvent, config: WebhookConfig, repo_label: str) -> NormalizedEvent:
    kind = classify_event_kind(event.event_type, config)
    if kind is None:
        raise EventParseError("WEBHOOK_EVENT_INVALID", 422, "无法判定事件种类")
    if not is_action_allowed(event.action, kind):
        return NormalizedEvent(
            event_id=event.event_id,
            event_kind=kind,
            repository_identifier=event.repository_identifier,
            repo_label=repo_label,
            pull_request_number=event.pull_request_number,
            base_sha=event.base_sha,
            head_sha=event.head_sha,
            changed_files=(),
            changed_files_source=ChangedFilesSource.NONE,
            changed_files_available=False,
            illegal_paths=(),
            signature_verified=True,
            occurred_at=event.received_at,
        )
    paths, source, _, illegal = extract_changed_files_with_statuses(event.raw_payload, config)
    available = source in (ChangedFilesSource.PAYLOAD, ChangedFilesSource.PAYLOAD_LISTS) and bool(paths)
    return NormalizedEvent(
        event_id=event.event_id,
        event_kind=kind,
        repository_identifier=event.repository_identifier,
        repo_label=repo_label,
        pull_request_number=event.pull_request_number,
        base_sha=event.base_sha,
        head_sha=event.head_sha,
        changed_files=paths if available else (),
        changed_files_source=source,
        changed_files_available=available,
        illegal_paths=illegal,
        signature_verified=True,
        occurred_at=event.received_at,
    )


def build_manifest(paths: Sequence[str], statuses: Mapping[str, str] | None = None) -> tuple[str, int]:
    status_map = dict(statuses or {})
    lines: list[str] = []
    for path in paths:
        status = status_map.get(path, "M")
        if status not in {"A", "M", "D"}:
            status = "M"
        lines.append(f"{status} {path}")
    text = "\n".join(lines) + ("\n" if lines else "")
    return text, len(lines)
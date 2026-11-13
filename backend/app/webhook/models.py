from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from ..integrations.models import PublishResult

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class WebhookError(Exception):
    def __init__(self, code: str, status_code: int, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.detail = detail


class EventKind(Enum):
    CREATED = "created"
    UPDATED = "updated"


class ChangedFilesSource(Enum):
    PAYLOAD = "payload"
    PAYLOAD_LISTS = "payload_lists"
    OPENAPI = "openapi"
    NONE = "none"


class CheckOutcome(Enum):
    OK = "正常"
    PARTIAL_DEGRADED = "部分降级"
    INPUT_ERROR = "输入错误"
    NOT_EXECUTED = "未执行"
    TIMEOUT = "超时"
    FAILED = "失败"


class DeliveryStatus(Enum):
    DELIVERED = "delivered"
    MOCK_DELIVERED = "mock_delivered"
    SKIPPED = "skipped"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FAILED = "failed"
    DEGRADED = "degraded"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_id: str
    event_type: str
    action: str | None
    repository_identifier: str
    pull_request_number: int
    base_sha: str | None
    head_sha: str | None
    raw_payload: Mapping[str, object]
    headers: Mapping[str, str]
    body_sha256: str
    received_at: datetime.datetime
    event_id_source: str

    def __post_init__(self) -> None:
        if not (1 <= len(self.event_id) <= 200):
            raise ValueError("event_id 长度必须在 1～200 之间")
        if not (1 <= len(self.event_type) <= 100):
            raise ValueError("event_type 长度必须在 1～100 之间")
        if self.action is not None and len(self.action) > 50:
            raise ValueError("action 长度不能超过 50")
        if not (1 <= len(self.repository_identifier) <= 300):
            raise ValueError("repository_identifier 长度必须在 1～300 之间")
        if self.pull_request_number <= 0:
            raise ValueError("pull_request_number 必须为正整数")
        if not _SHA_RE.match(self.body_sha256):
            raise ValueError("body_sha256 必须是 64 位小写十六进制")
        if self.event_id_source not in {"payload", "delivery_header", "content_hash"}:
            raise ValueError("event_id_source 非法")


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    event_id: str
    event_kind: EventKind
    repository_identifier: str
    repo_label: str
    pull_request_number: int
    base_sha: str | None
    head_sha: str | None
    changed_files: tuple[str, ...]
    changed_files_source: ChangedFilesSource
    changed_files_available: bool
    illegal_paths: tuple[str, ...]
    signature_verified: bool
    occurred_at: datetime.datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.event_kind, EventKind):
            raise ValueError("event_kind 必须是 EventKind")
        if not isinstance(self.changed_files_source, ChangedFilesSource):
            raise ValueError("changed_files_source 必须是 ChangedFilesSource")
        if self.signature_verified is not True:
            raise ValueError("signature_verified 必须为 True")
        if any(char in self.repo_label for char in ("/", "\\", ":")):
            raise ValueError("repo_label 不能包含路径分隔符")


@dataclass(frozen=True, slots=True)
class ReviewJob:
    event: NormalizedEvent
    repo_root: Path
    manifest_text: str
    entry_count: int
    created_at: datetime.datetime
    attempt: int
    request_id: str

    def __post_init__(self) -> None:
        lines = [line for line in self.manifest_text.splitlines() if line]
        if self.entry_count != len(lines):
            raise ValueError("entry_count 与清单行数不一致")
        if self.attempt < 1:
            raise ValueError("attempt 必须大于等于 1")
        if not (1 <= len(self.request_id) <= 64):
            raise ValueError("request_id 长度必须在 1～64 之间")


@dataclass(frozen=True, slots=True)
class CommentPayload:
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

    def __post_init__(self) -> None:
        if not (1 <= len(self.markdown) <= 100_000):
            raise ValueError("评论正文长度必须在 1～100000 之间")
        if self.char_count != len(self.markdown):
            raise ValueError("char_count 与正文长度不一致")
        if not self.markdown.endswith(self.marker):
            raise ValueError("marker 必须位于评论正文末尾")
        for value in (
            self.omitted_must_fix,
            self.omitted_suggestions,
            self.must_fix_count,
            self.suggestion_count,
            self.issue_count,
            self.skipped_file_count,
            self.degraded_module_count,
        ):
            if value < 0:
                raise ValueError("评论计数不能为负")


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    event_id: str
    request_id: str
    repo_label: str
    pull_request_number: int
    received_at: datetime.datetime
    finished_at: datetime.datetime | None
    duration_ms: int
    signature_result: str
    check_status: str
    must_fix_count: int
    suggestion_count: int
    issue_count: int
    changed_files_source: str
    changed_file_count: int
    comment_chars: int
    truncated: bool
    delivery_status: str
    publish_result: PublishResult | None = None
    error_code: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.check_status not in {item.value for item in CheckOutcome}:
            raise ValueError("check_status 非法")
        if self.delivery_status not in {item.value for item in DeliveryStatus}:
            raise ValueError("delivery_status 非法")
        if self.duration_ms < 0:
            raise ValueError("duration_ms 不能为负")


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    status_code: int
    body: dict[str, object]
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not (100 <= self.status_code <= 599):
            raise ValueError("status_code 非法")


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: str
    service: str
    version: str
    secret_configured: bool
    signature_algorithm: str
    openapi_mode: str
    engine: str
    queue_depth: int
    queue_capacity: int
    dedup_size: int
    allowed_repo_count: int
    recent_delivery_failures: int
    time: str

    def __post_init__(self) -> None:
        if self.status not in {"ok", "degraded"}:
            raise ValueError("health status 非法")
        if self.service != "repoguard-webhook":
            raise ValueError("service 固定为 repoguard-webhook")
        if self.version != "1.0.0":
            raise ValueError("version 固定为 1.0.0")


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def format_utc(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()
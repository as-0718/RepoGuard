from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from ..api.settings import WebSettings
from ..core.rules.common.config import RuleConfig
from ..core.rules.common.models import CheckReport
from ..core.rules.engine import run_check
from ..integrations.mock import MockOpenApiAdapter
from ..integrations.models import OpenApiMode, PublishResult, validate_profile
from ..integrations.openapi import ConfigurableOpenApiAdapter, OpenApiAdapter
from .idempotency import IdempotencyRegistry, ReservationState
from .models import (
    ChangedFilesSource,
    CheckOutcome,
    CommentPayload,
    DeliveryRecord,
    DeliveryStatus,
    HealthSnapshot,
    IngestOutcome,
    NormalizedEvent,
    ReviewJob,
    WebhookEvent,
    WebhookError,
    format_utc,
    utc_now,
)
from .parser import (
    EventParseError,
    build_manifest,
    classify_event_kind,
    extract_changed_files_with_statuses,
    is_action_allowed,
    normalize_changed_path,
    normalize_event,
    parse_event,
    should_fetch_via_openapi_values,
)
from .queue import QueueFullError, ReviewQueue
from .render import RenderError, render_comment
from .security import RepoMappingError, resolve_event_repo, safe_repo_label
from .settings import WebhookConfig, config_summary
from .signature import secret_configured, verify_signature


class EngineUnavailableError(Exception):
    code: str = "ENGINE_UNAVAILABLE"
    status_code: int = 503


class EngineRunner(Protocol):
    def __call__(
        self,
        manifest_text: str,
        repo_root: str | Path,
        config: RuleConfig | None = None,
    ) -> CheckReport: ...


def get_engine() -> EngineRunner:
    if not callable(run_check):
        raise EngineUnavailableError("规则引擎当前不可用")
    return run_check


class WebhookService:
    def __init__(
        self,
        config: WebhookConfig,
        web_settings: WebSettings,
        *,
        runner: EngineRunner | None = None,
        adapter: OpenApiAdapter | None = None,
        registry: IdempotencyRegistry | None = None,
        queue: ReviewQueue | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        self._web_settings = web_settings
        self._runner = runner
        if self._runner is None:
            try:
                self._runner = get_engine()
            except EngineUnavailableError:
                self._runner = None
        self._adapter = adapter
        if self._adapter is None:
            if config.openapi_mode is OpenApiMode.MOCK:
                self._adapter = MockOpenApiAdapter()
            elif config.openapi_mode is OpenApiMode.LIVE and config.openapi_profile is not None:
                try:
                    self._adapter = ConfigurableOpenApiAdapter(config.openapi_profile)
                except Exception:
                    self._adapter = None
        self._registry = registry or IdempotencyRegistry(
            config.idempotency_ttl_seconds,
            config.idempotency_capacity,
            stale_after_seconds=config.task_timeout_seconds + 30,
            clock=clock,
        )
        self._queue = queue or ReviewQueue(
            config.queue_capacity,
            config.worker_concurrency,
            self.process_job,
            task_timeout_seconds=config.task_timeout_seconds,
            clock=clock,
        )
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._logger = logging.getLogger("repoguard.webhook.service")
        self._records: deque[DeliveryRecord] = deque(maxlen=config.record_buffer_size)
        self._records_lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._queue.start()

    def shutdown(self, timeout: float | None = None) -> None:
        self._queue.shutdown(self._config.stop_timeout_seconds if timeout is None else timeout)

    def _error(self, request_id: str, code: str, status: int, message: str, detail: str | None = None) -> IngestOutcome:
        return IngestOutcome(
            status,
            {
                "status": "rejected",
                "error": {"code": code, "message": message, "detail": detail},
                "request_id": request_id,
            },
            code,
        )

    def _accepted(self, request_id: str, event_id: str, action: str, duplicate: bool = False, status: str = "accepted") -> IngestOutcome:
        return IngestOutcome(
            202,
            {
                "status": status,
                "action": action,
                "event_id": event_id,
                "request_id": request_id,
                "duplicate": duplicate,
                "message": "事件已接收" if not duplicate else "事件已处理，已跳过重复回评",
            },
        )

    def _job_for(
        self,
        event: WebhookEvent,
        normalized: NormalizedEvent,
        repo_root: Path,
        request_id: str,
        attempt: int,
    ) -> ReviewJob:
        if normalized.changed_files_source in (ChangedFilesSource.PAYLOAD, ChangedFilesSource.PAYLOAD_LISTS):
            _, _, statuses, _ = extract_changed_files_with_statuses(event.raw_payload, self._config)
            manifest, count = build_manifest(normalized.changed_files, statuses)
        else:
            manifest, count = "", 0
        return ReviewJob(
            event=normalized,
            repo_root=repo_root,
            manifest_text=manifest,
            entry_count=count,
            created_at=utc_now(),
            attempt=attempt,
            request_id=request_id,
        )

    def _record_not_attempted(
        self,
        normalized: NormalizedEvent,
        request_id: str,
        reason: str,
        check_status: str = CheckOutcome.NOT_EXECUTED.value,
    ) -> DeliveryRecord:
        now = utc_now()
        return DeliveryRecord(
            event_id=normalized.event_id,
            request_id=request_id,
            repo_label=normalized.repo_label,
            pull_request_number=normalized.pull_request_number,
            received_at=now,
            finished_at=now,
            duration_ms=0,
            signature_result="ok",
            check_status=check_status,
            must_fix_count=0,
            suggestion_count=0,
            issue_count=0,
            changed_files_source=normalized.changed_files_source.value,
            changed_file_count=len(normalized.changed_files),
            comment_chars=0,
            truncated=False,
            delivery_status=DeliveryStatus.DEGRADED.value,
            error_code=None,
            reason=reason,
        )

    def _ingest(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        request_id: str,
        *,
        sync: bool,
    ) -> IngestOutcome:
        if not self._config.enabled:
            return self._error(request_id, "WEBHOOK_DISABLED", 503, "Webhook 已禁用")
        if not secret_configured(self._config):
            return self._error(request_id, "WEBHOOK_SECRET_NOT_CONFIGURED", 503, "Webhook 签名密钥未配置")
        if self._config.openapi_mode is OpenApiMode.LIVE and self._adapter is None:
            missing = validate_profile(self._config.openapi_profile, OpenApiMode.LIVE)
            detail = "缺失字段：" + ", ".join(missing) if missing else "OpenAPI 适配器不可用"
            return self._error(request_id, "OPENAPI_NOT_CONFIGURED", 503, "OpenAPI 配置不完整", detail)
        try:
            verify_signature(headers, raw_body, self._config)
        except WebhookError as exc:
            return self._error(request_id, exc.code, exc.status_code, exc.message, exc.detail)
        try:
            event = parse_event(raw_body, headers, self._config)
            repo_label = safe_repo_label(event.repository_identifier)
            normalized = normalize_event(event, self._config, repo_label)
        except WebhookError as exc:
            return self._error(request_id, exc.code, exc.status_code, exc.message, exc.detail)
        except ValueError:
            return self._error(request_id, "WEBHOOK_EVENT_INVALID", 422, "事件字段不合法")

        if event.event_type.casefold() not in {item.casefold() for item in self._config.event_types}:
            return self._accepted(request_id, event.event_id, "skipped", status="ignored")
        kind = classify_event_kind(event.event_type, self._config)
        if kind is None:
            return self._error(request_id, "WEBHOOK_EVENT_INVALID", 422, "无法判定事件种类")
        if not is_action_allowed(event.action, kind):
            return self._accepted(request_id, event.event_id, "skipped", status="ignored")

        try:
            repo_root = resolve_event_repo(event.repository_identifier, self._web_settings, self._config)
        except RepoMappingError as exc:
            return self._error(request_id, exc.code, exc.status_code, exc.message, exc.detail)

        reservation = self._registry.reserve(
            event.event_id,
            event.body_sha256,
            allow_retry_failed=self._config.idempotency_retry_failed,
        )
        if reservation.state is ReservationState.CONFLICT:
            return self._error(request_id, "WEBHOOK_EVENT_CONFLICT", 409, "同一事件标识携带了不同内容")
        if reservation.state in {
            ReservationState.DUPLICATE_PROCESSING,
            ReservationState.DUPLICATE_DONE,
            ReservationState.DUPLICATE_FAILED,
        }:
            return self._accepted(request_id, event.event_id, "skipped", duplicate=True, status="duplicate")

        job = self._job_for(event, normalized, repo_root, request_id, reservation.attempt)
        if job.entry_count == 0 and normalized.changed_files_source is not ChangedFilesSource.OPENAPI:
            self._registry.complete(event.event_id)
            record = self._record_not_attempted(normalized, request_id, "变更清单为空，未执行检查")
            self._remember(record)
            self._notify_unexecuted(normalized, "变更清单为空，未执行检查")
            return self._accepted(request_id, event.event_id, "not_attempted", status="degraded")
        if job.entry_count > self._config.max_changed_files:
            self._registry.fail(event.event_id, "WEBHOOK_CHANGED_FILES_TOO_MANY")
            record = self._record_not_attempted(normalized, request_id, "变更文件数量超过上限，未执行检查")
            self._remember(record)
            self._notify_unexecuted(normalized, "变更文件数量超过上限，未执行检查")
            return self._accepted(request_id, event.event_id, "not_attempted", status="degraded")

        try:
            if sync:
                record = self._queue.run_now(job, self._config.task_timeout_seconds)
                if record.check_status == CheckOutcome.TIMEOUT.value:
                    self._remember(record)
                if record.delivery_status in {DeliveryStatus.DELIVERED.value, DeliveryStatus.MOCK_DELIVERED.value}:
                    return IngestOutcome(200, {"status": "completed", "action": "delivered", "event_id": event.event_id, "request_id": request_id, "duplicate": False, "message": "检查完成并回写"})
                if record.check_status == CheckOutcome.TIMEOUT.value:
                    return IngestOutcome(504, {"status": "timeout", "action": "not_attempted", "event_id": event.event_id, "request_id": request_id, "duplicate": False, "message": "检查超时"})
                if record.delivery_status == DeliveryStatus.FAILED.value:
                    return IngestOutcome(502, {"status": "failed", "action": "failed", "event_id": event.event_id, "request_id": request_id, "duplicate": False, "message": "回写失败"})
                return self._accepted(request_id, event.event_id, "not_attempted", status="degraded")
            self._queue.submit(job)
        except QueueFullError:
            self._registry.rollback(event.event_id, reservation.previous_state)
            return self._error(request_id, "WEBHOOK_BUSY", 429, "检查队列已满，请稍后重试")
        return self._accepted(request_id, event.event_id, "queued", status="accepted")

    def handle_ingest(self, raw_body: bytes, headers: Mapping[str, str], request_id: str) -> IngestOutcome:
        return self._ingest(raw_body, headers, request_id, sync=False)

    def handle_ingest_sync(self, raw_body: bytes, headers: Mapping[str, str], request_id: str) -> IngestOutcome:
        return self._ingest(raw_body, headers, request_id, sync=True)

    def _remember(self, record: DeliveryRecord) -> None:
        with self._records_lock:
            self._records.append(record)

    def _notify_unexecuted(self, event: NormalizedEvent, reason: str) -> None:
        if not self._config.notify_on_failure or self._adapter is None or self._config.openapi_mode is OpenApiMode.DISABLED:
            return
        try:
            payload = render_comment(None, event, self._config, executed=False, status_reason=reason)
            self._adapter.publish_comment(event.repository_identifier, event.pull_request_number, payload)
        except Exception:
            self._logger.info(json.dumps({"event": "notify_failed", "event_id": event.event_id}, ensure_ascii=False))

    def process_job(self, job: ReviewJob) -> DeliveryRecord:
        started = self._clock()
        event = job.event
        manifest_text = job.manifest_text
        entry_count = job.entry_count
        if event.changed_files_source is ChangedFilesSource.OPENAPI:
            if self._adapter is None:
                record = self._record_not_attempted(event, job.request_id, "OpenAPI 适配器不可用，未执行检查")
                self._registry.fail(event.event_id, "OPENAPI_NOT_CONFIGURED")
                self._remember(record)
                return record
            paths = self._adapter.fetch_changed_files(
                event.repository_identifier,
                event.base_sha or "",
                event.head_sha or "",
            )
            if not paths:
                record = self._record_not_attempted(event, job.request_id, "无法获取变更清单，未执行检查")
                self._registry.fail(event.event_id, "WEBHOOK_CHANGED_FILES_UNAVAILABLE")
                self._remember(record)
                self._notify_unexecuted(event, "无法获取变更清单，未执行检查")
                return record
            normalized_paths: list[str] = []
            for item in paths:
                normalized, error = normalize_changed_path(item)
                if error is None and normalized is not None:
                    normalized_paths.append(normalized)
            manifest_text, entry_count = build_manifest(normalized_paths)
        if entry_count == 0 or entry_count > self._config.max_changed_files:
            record = self._record_not_attempted(event, job.request_id, "变更清单为空或超过上限，未执行检查")
            self._registry.fail(event.event_id, "WEBHOOK_CHANGED_FILES_INVALID")
            self._remember(record)
            self._notify_unexecuted(event, "变更清单为空或超过上限，未执行检查")
            return record

        report: CheckReport | None = None
        failure_code: str | None = None
        failure_reason: str | None = None
        if self._runner is None:
            failure_code = "ENGINE_UNAVAILABLE"
            failure_reason = "规则引擎不可用，检查未执行"
        else:
            try:
                report = self._runner(manifest_text, job.repo_root, None)
            except Exception:
                failure_code = "WEBHOOK_ENGINE_ERROR"
                failure_reason = "规则引擎执行异常，检查未完成"

        check_status = report.status.value if report is not None else CheckOutcome.FAILED.value
        if report is None:
            record = DeliveryRecord(
                event_id=event.event_id,
                request_id=job.request_id,
                repo_label=event.repo_label,
                pull_request_number=event.pull_request_number,
                received_at=job.created_at,
                finished_at=utc_now(),
                duration_ms=int((self._clock() - started) * 1000),
                signature_result="ok",
                check_status=check_status,
                must_fix_count=0,
                suggestion_count=0,
                issue_count=0,
                changed_files_source=event.changed_files_source.value,
                changed_file_count=entry_count,
                comment_chars=0,
                truncated=False,
                delivery_status=DeliveryStatus.FAILED.value,
                publish_result=None,
                error_code=failure_code,
                reason=failure_reason,
            )
            self._registry.fail(event.event_id, failure_code or "WEBHOOK_ENGINE_ERROR")
            self._remember(record)
            if self._config.notify_on_failure:
                self._notify_unexecuted(event, failure_reason or "检查未执行")
            return record

        try:
            payload = render_comment(
                report,
                event,
                self._config,
                executed=True,
                illegal_paths=event.illegal_paths,
                absolute_roots=(str(job.repo_root),),
            )
        except RenderError:
            record = DeliveryRecord(
                event_id=event.event_id,
                request_id=job.request_id,
                repo_label=event.repo_label,
                pull_request_number=event.pull_request_number,
                received_at=job.created_at,
                finished_at=utc_now(),
                duration_ms=int((self._clock() - started) * 1000),
                signature_result="ok",
                check_status=check_status,
                must_fix_count=report.summary.must_fix_count,
                suggestion_count=report.summary.suggestion_count,
                issue_count=report.summary.issue_count,
                changed_files_source=event.changed_files_source.value,
                changed_file_count=entry_count,
                comment_chars=0,
                truncated=False,
                delivery_status=DeliveryStatus.FAILED.value,
                error_code="WEBHOOK_COMMENT_RENDER_FAILED",
                reason="评论渲染失败",
            )
            self._registry.fail(event.event_id, "WEBHOOK_COMMENT_RENDER_FAILED")
            self._remember(record)
            return record

        if report.summary.issue_count == 0 and not self._config.notify_on_clean:
            record = DeliveryRecord(
                event_id=event.event_id,
                request_id=job.request_id,
                repo_label=event.repo_label,
                pull_request_number=event.pull_request_number,
                received_at=job.created_at,
                finished_at=utc_now(),
                duration_ms=int((self._clock() - started) * 1000),
                signature_result="ok",
                check_status=check_status,
                must_fix_count=report.summary.must_fix_count,
                suggestion_count=report.summary.suggestion_count,
                issue_count=report.summary.issue_count,
                changed_files_source=event.changed_files_source.value,
                changed_file_count=entry_count,
                comment_chars=0,
                truncated=False,
                delivery_status=DeliveryStatus.SKIPPED.value,
                reason="无问题且配置为不回报",
            )
            self._registry.complete(event.event_id)
            self._remember(record)
            return record

        publish_result: PublishResult | None = None
        delivery_status = DeliveryStatus.SKIPPED.value
        reason: str | None = None
        if self._config.openapi_mode is OpenApiMode.DISABLED:
            delivery_status = DeliveryStatus.SKIPPED.value
            reason = "OpenAPI 未启用"
        elif self._adapter is None:
            delivery_status = DeliveryStatus.FAILED.value
            reason = "OpenAPI 适配器不可用"
        else:
            try:
                publish_result = self._adapter.publish_comment(
                    event.repository_identifier,
                    event.pull_request_number,
                    payload,
                )
            except Exception:
                publish_result = PublishResult(False, None, "OPENAPI_UNAVAILABLE", "OpenAPI 回写失败")
            delivery_status = (
                DeliveryStatus.MOCK_DELIVERED.value
                if self._config.openapi_mode is OpenApiMode.MOCK and publish_result.success
                else DeliveryStatus.DELIVERED.value
                if publish_result.success
                else DeliveryStatus.FAILED.value
            )
            if not publish_result.success:
                reason = publish_result.error_message or "OpenAPI 回写失败"

        record = DeliveryRecord(
            event_id=event.event_id,
            request_id=job.request_id,
            repo_label=event.repo_label,
            pull_request_number=event.pull_request_number,
            received_at=job.created_at,
            finished_at=utc_now(),
            duration_ms=int((self._clock() - started) * 1000),
            signature_result="ok",
            check_status=check_status,
            must_fix_count=report.summary.must_fix_count,
            suggestion_count=report.summary.suggestion_count,
            issue_count=report.summary.issue_count,
            changed_files_source=event.changed_files_source.value,
            changed_file_count=entry_count,
            comment_chars=payload.char_count,
            truncated=payload.truncated,
            delivery_status=delivery_status,
            publish_result=publish_result,
            error_code=publish_result.error_code if publish_result and not publish_result.success else None,
            reason=reason,
        )
        if delivery_status == DeliveryStatus.FAILED.value:
            self._registry.fail(event.event_id, record.error_code or "OPENAPI_UNAVAILABLE")
        else:
            self._registry.complete(event.event_id)
        self._remember(record)
        self._logger.info(
            json.dumps(
                {
                    "request_id": job.request_id,
                    "event_id": event.event_id,
                    "repo": event.repo_label,
                    "check_status": check_status,
                    "delivery_status": delivery_status,
                },
                ensure_ascii=False,
            )
        )
        return record

    def health_snapshot(self) -> HealthSnapshot:
        snapshot = self._registry.snapshot()
        with self._records_lock:
            failures = sum(
                1
                for record in self._records
                if record.delivery_status in {DeliveryStatus.FAILED.value, DeliveryStatus.DEGRADED.value}
            )
        healthy = (
            self._config.enabled
            and secret_configured(self._config)
            and self._runner is not None
            and (self._config.openapi_mode is not OpenApiMode.LIVE or self._adapter is not None)
        )
        return HealthSnapshot(
            status="ok" if healthy else "degraded",
            service="repoguard-webhook",
            version="1.0.0",
            secret_configured=secret_configured(self._config),
            signature_algorithm="HMAC-SHA256",
            openapi_mode=self._config.openapi_mode.value,
            engine="available" if self._runner is not None else "unavailable",
            queue_depth=self._queue.depth(),
            queue_capacity=self._config.queue_capacity,
            dedup_size=snapshot.get("size", 0),
            allowed_repo_count=len(self._web_settings.allowed_repo_roots),
            recent_delivery_failures=failures,
            time=format_utc(utc_now()),
        )

    def recent_records(self, limit: int = 50) -> tuple[DeliveryRecord, ...]:
        with self._records_lock:
            values = list(self._records)
        return tuple(values[-max(1, limit):])
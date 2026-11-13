from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class ReservationState(Enum):
    NEW = "new"
    RETRY_ALLOWED = "retry_allowed"
    DUPLICATE_PROCESSING = "duplicate_processing"
    DUPLICATE_DONE = "duplicate_done"
    DUPLICATE_FAILED = "duplicate_failed"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ReservationResult:
    state: ReservationState
    attempt: int
    first_seen: float
    body_sha256: str
    previous_state: str | None
    error_code: str | None


@dataclass(slots=True)
class _Record:
    body_sha256: str
    state: str
    first_seen: float
    updated_at: float
    attempt: int
    error_code: str | None = None


class IdempotencyRegistry:
    def __init__(
        self,
        ttl_seconds: int,
        capacity: int,
        *,
        stale_after_seconds: float = 150.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or capacity <= 0:
            raise ValueError("幂等参数必须为正数")
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._stale_after = stale_after_seconds
        self._clock = clock or time.monotonic
        self._records: OrderedDict[str, _Record] = OrderedDict()
        self._lock = threading.Lock()
        self._evicted = 0
        self._overflow = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def evicted_count(self) -> int:
        with self._lock:
            return self._evicted

    def _expired(self, record: _Record, now: float) -> bool:
        return now >= record.first_seen + self._ttl

    def _evict(self, now: float) -> None:
        expired = [key for key, record in self._records.items() if self._expired(record, now)]
        for key in expired:
            self._records.pop(key, None)
            self._evicted += 1
        while len(self._records) > self._capacity:
            victim = None
            for key, record in self._records.items():
                if record.state != "PROCESSING":
                    victim = key
                    break
            if victim is None:
                self._overflow = len(self._records) - self._capacity
                break
            self._records.pop(victim, None)
            self._evicted += 1
            self._overflow = max(0, len(self._records) - self._capacity)

    def reserve(
        self,
        event_id: str,
        body_sha256: str,
        *,
        allow_retry_failed: bool = False,
    ) -> ReservationResult:
        if not event_id:
            raise ValueError("event_id 不能为空")
        with self._lock:
            now = self._clock()
            self._evict(now)
            record = self._records.get(event_id)
            if record is None:
                record = _Record(body_sha256, "PROCESSING", now, now, 1)
                self._records[event_id] = record
                self._records.move_to_end(event_id)
                self._evict(now)
                return ReservationResult(ReservationState.NEW, 1, now, body_sha256, None, None)
            if record.body_sha256 != body_sha256:
                return ReservationResult(
                    ReservationState.CONFLICT,
                    record.attempt,
                    record.first_seen,
                    record.body_sha256,
                    record.state,
                    "WEBHOOK_EVENT_CONFLICT",
                )
            if record.state == "PROCESSING":
                if now - record.updated_at > self._stale_after:
                    previous = record.state
                    record.state = "PROCESSING"
                    record.updated_at = now
                    record.attempt += 1
                    return ReservationResult(
                        ReservationState.NEW,
                        record.attempt,
                        record.first_seen,
                        record.body_sha256,
                        previous,
                        None,
                    )
                return ReservationResult(
                    ReservationState.DUPLICATE_PROCESSING,
                    record.attempt,
                    record.first_seen,
                    record.body_sha256,
                    record.state,
                    None,
                )
            if record.state == "DONE":
                return ReservationResult(
                    ReservationState.DUPLICATE_DONE,
                    record.attempt,
                    record.first_seen,
                    record.body_sha256,
                    record.state,
                    None,
                )
            if record.state == "FAILED":
                if allow_retry_failed:
                    previous = record.state
                    record.state = "PROCESSING"
                    record.updated_at = now
                    record.attempt += 1
                    record.error_code = None
                    return ReservationResult(
                        ReservationState.RETRY_ALLOWED,
                        record.attempt,
                        record.first_seen,
                        record.body_sha256,
                        previous,
                        None,
                    )
                return ReservationResult(
                    ReservationState.DUPLICATE_FAILED,
                    record.attempt,
                    record.first_seen,
                    record.body_sha256,
                    record.state,
                    record.error_code,
                )
            return ReservationResult(
                ReservationState.DUPLICATE_DONE,
                record.attempt,
                record.first_seen,
                record.body_sha256,
                record.state,
                record.error_code,
            )

    def complete(self, event_id: str) -> None:
        with self._lock:
            record = self._records.get(event_id)
            if record is not None:
                record.state = "DONE"
                record.updated_at = self._clock()
                self._records.move_to_end(event_id)

    def fail(self, event_id: str, error_code: str) -> None:
        with self._lock:
            record = self._records.get(event_id)
            if record is not None:
                record.state = "FAILED"
                record.updated_at = self._clock()
                record.error_code = error_code

    def rollback(self, event_id: str, previous_state: str | None) -> None:
        with self._lock:
            record = self._records.get(event_id)
            if record is None:
                return
            if previous_state is None:
                self._records.pop(event_id, None)
                return
            record.state = previous_state
            record.attempt = max(1, record.attempt - 1)
            record.updated_at = self._clock()

    def purge(self) -> int:
        with self._lock:
            now = self._clock()
            before = len(self._records)
            self._evict(now)
            return before - len(self._records)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            processing = sum(1 for record in self._records.values() if record.state == "PROCESSING")
            done = sum(1 for record in self._records.values() if record.state == "DONE")
            failed = sum(1 for record in self._records.values() if record.state == "FAILED")
            return {
                "size": len(self._records),
                "capacity": self._capacity,
                "evicted": self._evicted,
                "overflow": self._overflow,
                "processing": processing,
                "done": done,
                "failed": failed,
            }
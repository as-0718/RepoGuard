from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CacheMeta:
    cached: bool
    age_seconds: int
    refresh_throttled: bool


class CacheBusyError(Exception):
    pass


class CacheTimeoutError(Exception):
    pass


@dataclass(slots=True)
class _Entry:
    value: object
    stored_at: float
    expires_at: float


@dataclass(slots=True)
class _Flight:
    event: threading.Event
    value: object | None = None
    error: BaseException | None = None


class SnapshotCache:
    def __init__(
        self,
        ttl_seconds: int,
        capacity: int,
        *,
        max_concurrency: int = 2,
        queue_timeout_seconds: float = 5.0,
        refresh_min_interval_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = max(0, int(ttl_seconds))
        self._capacity = max(1, int(capacity))
        self._max_concurrency = max(1, int(max_concurrency))
        self._queue_timeout = max(0.0, float(queue_timeout_seconds))
        self._refresh_min_interval = max(0.0, float(refresh_min_interval_seconds))
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._inflight: dict[str, _Flight] = {}
        self._lock = threading.RLock()
        self._gate = threading.BoundedSemaphore(self._max_concurrency)
        self._counters = {
            "hits": 0,
            "misses": 0,
            "loads": 0,
            "failures": 0,
            "evictions": 0,
            "throttled": 0,
            "waits": 0,
            "busy": 0,
            "timeouts": 0,
        }

    def get(self, key: str) -> tuple[object | None, int]:
        with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is None:
                self._counters["misses"] += 1
                return None, 0
            if now >= entry.expires_at:
                self._entries.pop(key, None)
                self._counters["misses"] += 1
                return None, 0
            self._entries.move_to_end(key)
            self._counters["hits"] += 1
            return entry.value, int(max(0.0, now - entry.stored_at))

    def set(self, key: str, value: object) -> None:
        if self._ttl <= 0:
            return
        with self._lock:
            now = self._clock()
            if key in self._entries:
                self._entries.pop(key, None)
            elif len(self._entries) >= self._capacity:
                self._entries.popitem(last=False)
                self._counters["evictions"] += 1
            self._entries[key] = _Entry(value, now, now + self._ttl)

    def _purge_expired_locked(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if now >= entry.expires_at]
        for key in expired:
            self._entries.pop(key, None)
            self._counters["misses"] += 1

    def get_or_load(
        self,
        key: str,
        loader: Callable[[], T],
        *,
        force: bool = False,
        deadline: float | None = None,
    ) -> tuple[T, CacheMeta]:
        flight: _Flight | None = None
        leader = False
        with self._lock:
            now = self._clock()
            self._purge_expired_locked(now)
            entry = self._entries.get(key)
            if entry is not None:
                age = max(0.0, now - entry.stored_at)
                if not force or age < self._refresh_min_interval:
                    self._entries.move_to_end(key)
                    self._counters["hits"] += 1
                    throttled = bool(force and age < self._refresh_min_interval)
                    if throttled:
                        self._counters["throttled"] += 1
                    return entry.value, CacheMeta(True, int(age), throttled)
            flight = self._inflight.get(key)
            if flight is not None:
                self._counters["waits"] += 1
            else:
                flight = _Flight(threading.Event())
                self._inflight[key] = flight
                leader = True
                self._counters["misses"] += 1

        if not leader and flight is not None:
            timeout = None
            if deadline is not None:
                timeout = max(0.0, deadline - self._clock())
                if timeout == 0.0:
                    with self._lock:
                        self._counters["timeouts"] += 1
                    raise CacheTimeoutError("缓存等待超时")
            if not flight.event.wait(timeout):
                with self._lock:
                    self._counters["timeouts"] += 1
                raise CacheTimeoutError("缓存等待超时")
            if flight.error is not None:
                raise flight.error
            return flight.value, CacheMeta(False, 0, False)

        acquired = self._gate.acquire(timeout=self._queue_timeout)
        if not acquired:
            with self._lock:
                self._counters["busy"] += 1
                self._inflight.pop(key, None)
            flight.error = CacheBusyError("缓存并发已满")
            flight.event.set()
            raise CacheBusyError("缓存并发已满")

        try:
            if deadline is not None and self._clock() > deadline:
                with self._lock:
                    self._counters["timeouts"] += 1
                raise CacheTimeoutError("扫描超时")
            value = loader()
            if deadline is not None and self._clock() > deadline:
                with self._lock:
                    self._counters["timeouts"] += 1
                raise CacheTimeoutError("扫描超时，结果已丢弃")
            if self._ttl > 0:
                with self._lock:
                    now = self._clock()
                    if key in self._entries:
                        self._entries.pop(key, None)
                    elif len(self._entries) >= self._capacity:
                        self._entries.popitem(last=False)
                        self._counters["evictions"] += 1
                    self._entries[key] = _Entry(value, now, now + self._ttl)
            with self._lock:
                self._counters["loads"] += 1
                self._inflight.pop(key, None)
            flight.value = value
            flight.event.set()
            return value, CacheMeta(False, 0, False)
        except CacheTimeoutError:
            with self._lock:
                self._counters["timeouts"] += 1
                self._inflight.pop(key, None)
            flight.error = CacheTimeoutError("扫描超时，结果已丢弃")
            flight.event.set()
            raise
        except BaseException as exc:
            with self._lock:
                self._counters["failures"] += 1
                self._inflight.pop(key, None)
            flight.error = exc
            flight.event.set()
            raise
        finally:
            self._gate.release()

    def clear(self) -> None:
        with self._lock:
            flights = list(self._inflight.values())
            self._inflight.clear()
            self._entries.clear()
            for name in self._counters:
                self._counters[name] = 0
            for flight in flights:
                flight.error = CacheTimeoutError("缓存已清空")
                flight.event.set()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)
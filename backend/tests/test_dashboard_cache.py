from __future__ import annotations

import threading
import unittest

from app.dashboard.cache import CacheBusyError, CacheTimeoutError, SnapshotCache
from tests.webhook_helpers import FrozenClock

_COUNTER_NAMES = (
    "hits",
    "misses",
    "loads",
    "failures",
    "evictions",
    "throttled",
    "waits",
    "busy",
    "timeouts",
)


def _wait_until(predicate, attempts: int = 5000, interval: float = 0.001) -> bool:
    """在有限次数内让出 CPU，等待并发状态就绪（不使用 sleep 推进缓存时钟）。"""
    for _ in range(attempts):
        if predicate():
            return True
        threading.Event().wait(interval)
    return predicate()


class SnapshotCacheTests(unittest.TestCase):
    def _make_cache(
        self,
        *,
        ttl: int = 60,
        capacity: int = 4,
        clock: FrozenClock | None = None,
        max_concurrency: int = 2,
        queue_timeout: float = 5.0,
        refresh_interval: float = 10.0,
    ) -> SnapshotCache:
        return SnapshotCache(
            ttl,
            capacity,
            max_concurrency=max_concurrency,
            queue_timeout_seconds=queue_timeout,
            refresh_min_interval_seconds=refresh_interval,
            clock=clock if clock is not None else FrozenClock(1000.0),
        )

    # T-C01
    def test_get_missing_returns_none_and_zero(self):
        cache = self._make_cache()

        self.assertEqual(cache.get("missing"), (None, 0))
        stats = cache.stats()
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hits"], 0)

    # T-C02
    def test_set_then_get_returns_value_and_age(self):
        clock = FrozenClock(1000.0)
        cache = self._make_cache(clock=clock)

        cache.set("repo-a", {"files": 3})
        clock.advance(7)

        value, age = cache.get("repo-a")
        self.assertEqual(value, {"files": 3})
        self.assertIsInstance(age, int)
        self.assertEqual(age, 7)
        self.assertGreaterEqual(age, 0)
        self.assertEqual(cache.stats()["hits"], 1)

    # T-C03
    def test_ttl_expiry_removes_entry(self):
        clock = FrozenClock(1000.0)
        cache = self._make_cache(ttl=30, clock=clock)
        cache.set("repo-a", "snapshot")

        clock.advance(30)

        self.assertEqual(cache.get("repo-a"), (None, 0))
        self.assertEqual(cache.get("repo-a"), (None, 0))
        self.assertEqual(cache.stats()["misses"], 2)

        cache.set("repo-a", "fresh")
        self.assertEqual(cache.get("repo-a"), ("fresh", 0))

    # T-C04
    def test_ttl_zero_disables_store(self):
        cache = self._make_cache(ttl=0)
        calls: list[str] = []

        def loader() -> str:
            calls.append("load")
            return "value"

        cache.set("repo-a", "value")
        self.assertEqual(cache.get("repo-a"), (None, 0))

        first, first_meta = cache.get_or_load("repo-a", loader)
        second, second_meta = cache.get_or_load("repo-a", loader)

        self.assertEqual((first, second), ("value", "value"))
        self.assertFalse(first_meta.cached)
        self.assertFalse(second_meta.cached)
        self.assertEqual(len(calls), 2)
        self.assertEqual(cache.stats()["loads"], 2)

    # T-C05
    def test_lru_eviction_keeps_capacity(self):
        cache = self._make_cache(capacity=2)

        cache.set("a", "va")
        cache.set("b", "vb")
        cache.set("c", "vc")

        self.assertEqual(cache.get("a"), (None, 0))
        self.assertEqual(cache.get("b"), ("vb", 0))
        self.assertEqual(cache.get("c"), ("vc", 0))
        self.assertEqual(cache.stats()["evictions"], 1)

    # T-C06
    def test_lru_hit_refreshes_recency(self):
        cache = self._make_cache(capacity=2)

        cache.set("a", "va")
        cache.set("b", "vb")
        self.assertEqual(cache.get("a"), ("va", 0))

        cache.set("c", "vc")

        self.assertEqual(cache.get("b"), (None, 0))
        self.assertEqual(cache.get("a"), ("va", 0))
        self.assertEqual(cache.get("c"), ("vc", 0))
        self.assertEqual(cache.stats()["evictions"], 1)

    # T-C07
    def test_single_flight_same_key_loads_once(self):
        cache = self._make_cache(capacity=8)
        barrier = threading.Barrier(5)
        results: list[tuple[object, object]] = []
        errors: list[BaseException] = []
        loader_calls: list[int] = []

        def loader() -> str:
            loader_calls.append(1)
            self.assertTrue(_wait_until(lambda: cache.stats()["waits"] >= 4))
            return "payload"

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                results.append(cache.get_or_load("shared", loader))
            except BaseException as exc:  # pragma: no cover - 失败时用于报告
                errors.append(exc)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(loader_calls), 1)
        self.assertEqual(len(results), 5)
        self.assertEqual([item[0] for item in results], ["payload"] * 5)
        self.assertTrue(all(item[1].cached is False for item in results))
        stats = cache.stats()
        self.assertEqual(stats["loads"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["waits"], 4)

    # T-C08
    def test_single_flight_propagates_loader_error(self):
        cache = self._make_cache()
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        failure = ValueError("loader boom")
        loader_calls: list[int] = []

        def loader() -> str:
            loader_calls.append(1)
            self.assertTrue(_wait_until(lambda: cache.stats()["waits"] >= 1))
            raise failure

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                cache.get_or_load("shared", loader)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(loader_calls), 1)
        self.assertEqual(len(errors), 2)
        self.assertIs(errors[0], failure)
        self.assertIs(errors[1], failure)
        self.assertEqual(cache.stats()["failures"], 1)
        self.assertEqual(cache.stats()["loads"], 0)
        self.assertEqual(cache.get("shared"), (None, 0))

    # T-C09
    def test_failure_is_not_cached(self):
        cache = self._make_cache()
        calls: list[int] = []

        def loader() -> str:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("first failure")
            return "recovered"

        with self.assertRaises(RuntimeError):
            cache.get_or_load("repo-a", loader)

        self.assertEqual(cache.get("repo-a"), (None, 0))
        value, meta = cache.get_or_load("repo-a", loader)

        self.assertEqual(value, "recovered")
        self.assertFalse(meta.cached)
        self.assertEqual(len(calls), 2)
        stats = cache.stats()
        self.assertEqual(stats["failures"], 1)
        self.assertEqual(stats["loads"], 1)

    # T-C10
    def test_force_refresh_throttled_within_interval(self):
        clock = FrozenClock(1000.0)
        cache = self._make_cache(refresh_interval=10.0, clock=clock)
        calls: list[int] = []

        def loader() -> str:
            calls.append(1)
            return "value"

        cache.get_or_load("repo-a", loader)
        clock.advance(4)

        value, meta = cache.get_or_load("repo-a", loader, force=True)

        self.assertEqual(value, "value")
        self.assertTrue(meta.cached)
        self.assertEqual(meta.age_seconds, 4)
        self.assertTrue(meta.refresh_throttled)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.stats()["throttled"], 1)

    # T-C11
    def test_force_refresh_reloads_after_interval(self):
        clock = FrozenClock(1000.0)
        cache = self._make_cache(refresh_interval=10.0, clock=clock)
        calls: list[int] = []

        def loader() -> str:
            calls.append(1)
            return f"value-{len(calls)}"

        cache.get_or_load("repo-a", loader)
        clock.advance(10)

        value, meta = cache.get_or_load("repo-a", loader, force=True)

        self.assertEqual(value, "value-2")
        self.assertFalse(meta.cached)
        self.assertFalse(meta.refresh_throttled)
        self.assertEqual(len(calls), 2)
        self.assertEqual(cache.stats()["loads"], 2)

    # T-C12
    def test_deadline_exceeded_discards_late_result(self):
        clock = FrozenClock(100.0)
        cache = self._make_cache(clock=clock)

        def late_loader() -> str:
            clock.advance(10)
            return "late-result"

        deadline = clock() + 5

        with self.assertRaises(CacheTimeoutError):
            cache.get_or_load("repo-a", late_loader, deadline=deadline)

        self.assertEqual(cache.get("repo-a"), (None, 0))
        stats = cache.stats()
        self.assertEqual(stats["loads"], 0)
        self.assertEqual(stats["failures"], 0)
        self.assertEqual(stats["evictions"], 0)
        self.assertGreaterEqual(stats["timeouts"], 1)

    # T-C13
    def test_queue_timeout_raises_busy(self):
        cache = self._make_cache(max_concurrency=1, queue_timeout=0.0)
        entered = threading.Event()
        release = threading.Event()
        thread_errors: list[BaseException] = []

        def loader() -> str:
            entered.set()
            self.assertTrue(release.wait(5))
            return "held"

        def holder() -> None:
            try:
                cache.get_or_load("hold", loader)
            except BaseException as exc:  # pragma: no cover - 失败时用于报告
                thread_errors.append(exc)

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(CacheBusyError):
                cache.get_or_load("other", lambda: "never")
            self.assertEqual(cache.stats()["busy"], 1)
        finally:
            release.set()
            thread.join(10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(thread_errors, [])

    # T-C14
    def test_stats_counters_increment(self):
        clock = FrozenClock(1000.0)
        cache = self._make_cache(
            capacity=2,
            clock=clock,
            max_concurrency=1,
            queue_timeout=0.0,
            refresh_interval=10.0,
        )
        loaded: list[str] = []

        def ok_loader() -> str:
            loaded.append("ok")
            return "ok"

        self.assertEqual(cache.get("missing"), (None, 0))
        self.assertEqual(cache.get_or_load("k1", ok_loader)[0], "ok")
        self.assertEqual(cache.get_or_load("k1", ok_loader)[0], "ok")
        self.assertEqual(cache.get_or_load("k1", ok_loader, force=True)[0], "ok")
        self.assertEqual(len(loaded), 1)

        def failing() -> str:
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            cache.get_or_load("bad", failing)

        entered = threading.Event()
        release = threading.Event()
        thread_errors: list[BaseException] = []

        def slow_loader() -> str:
            entered.set()
            self.assertTrue(release.wait(5))
            loaded.append("slow")
            return "slow"

        def leader() -> None:
            try:
                cache.get_or_load("slow", slow_loader)
            except BaseException as exc:  # pragma: no cover - 失败时用于报告
                thread_errors.append(exc)

        thread = threading.Thread(target=leader, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(CacheBusyError):
                cache.get_or_load("other", ok_loader)
            with self.assertRaises(CacheTimeoutError):
                cache.get_or_load("slow", ok_loader, deadline=clock() - 1.0)
            self.assertEqual(thread_errors, [])
        finally:
            release.set()
            thread.join(10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(thread_errors, [])

        cache.set("k2", "v2")

        self.assertEqual(
            cache.stats(),
            {
                "hits": 2,
                "misses": 5,
                "loads": 2,
                "failures": 1,
                "evictions": 1,
                "throttled": 1,
                "waits": 1,
                "busy": 1,
                "timeouts": 1,
            },
        )

    # T-C15
    def test_clear_resets_entries_and_stats(self):
        cache = self._make_cache(capacity=4, clock=FrozenClock(0.0))
        cache.set("k", "v")
        cache.set("p", "w")
        self.assertEqual(cache.get("k"), ("v", 0))
        self.assertEqual(cache.get("p"), ("w", 0))
        self.assertEqual(cache.stats()["hits"], 2)

        entered = threading.Event()
        release = threading.Event()
        waiter_done = threading.Event()
        waiter_errors: list[BaseException] = []
        leader_errors: list[BaseException] = []

        def loader() -> str:
            entered.set()
            self.assertTrue(release.wait(5))
            return "late"

        def leader() -> None:
            try:
                cache.get_or_load("flight", loader)
            except BaseException as exc:  # pragma: no cover - 失败时用于报告
                leader_errors.append(exc)

        def waiter() -> None:
            try:
                cache.get_or_load("flight", lambda: "never")
            except BaseException as exc:
                waiter_errors.append(exc)
            finally:
                waiter_done.set()

        leader_thread = threading.Thread(target=leader, daemon=True)
        leader_thread.start()
        self.assertTrue(entered.wait(5))
        waiter_thread = threading.Thread(target=waiter, daemon=True)
        waiter_thread.start()
        try:
            self.assertTrue(_wait_until(lambda: cache.stats()["waits"] >= 1))
            cache.clear()

            self.assertEqual(cache.stats(), {name: 0 for name in _COUNTER_NAMES})
            self.assertEqual(cache.get("k"), (None, 0))
            self.assertEqual(cache.get("p"), (None, 0))
            after_get = cache.stats()
            self.assertEqual(after_get["misses"], 2)
            self.assertEqual(after_get["hits"], 0)
            self.assertEqual(after_get["loads"], 0)
        finally:
            self.assertTrue(waiter_done.wait(5))
            release.set()
            leader_thread.join(10)
            waiter_thread.join(10)

        self.assertFalse(waiter_thread.is_alive())
        self.assertEqual(leader_errors, [])
        self.assertEqual(len(waiter_errors), 1)
        self.assertIsInstance(waiter_errors[0], CacheTimeoutError)


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from collections.abc import Callable

from .models import (
    CheckOutcome,
    DeliveryRecord,
    DeliveryStatus,
    ReviewJob,
    utc_now,
)


class QueueFullError(Exception):
    code: str = "WEBHOOK_BUSY"
    status_code: int = 429


class TaskTimeoutError(Exception):
    pass


class ReviewQueue:
    def __init__(
        self,
        capacity: int,
        concurrency: int,
        handler: Callable[[ReviewJob], DeliveryRecord],
        *,
        task_timeout_seconds: float,
        clock: Callable[[], float] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if capacity < 1 or concurrency < 1:
            raise ValueError("队列容量与并发数必须为正")
        self._capacity = capacity
        self._concurrency = concurrency
        self._handler = handler
        self._timeout = task_timeout_seconds
        self._clock = clock or time.monotonic
        self._logger = logger or logging.getLogger("repoguard.webhook.queue")
        self._queue: queue.Queue[ReviewJob] = queue.Queue(maxsize=capacity)
        self._semaphore = threading.BoundedSemaphore(concurrency)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="repoguard-webhook",
        )
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for index in range(self._concurrency):
                worker = threading.Thread(
                    target=self._worker,
                    name=f"repoguard-webhook-worker-{index}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def submit(self, job: ReviewJob) -> None:
        self.start()
        try:
            self._queue.put_nowait(job)
        except queue.Full as exc:
            raise QueueFullError("检查队列已满") from exc

    def _timeout_record(self, job: ReviewJob, reason: str) -> DeliveryRecord:
        return DeliveryRecord(
            event_id=job.event.event_id,
            request_id=job.request_id,
            repo_label=job.event.repo_label,
            pull_request_number=job.event.pull_request_number,
            received_at=job.created_at,
            finished_at=utc_now(),
            duration_ms=0,
            signature_result="ok",
            check_status=CheckOutcome.TIMEOUT.value,
            must_fix_count=0,
            suggestion_count=0,
            issue_count=0,
            changed_files_source=job.event.changed_files_source.value,
            changed_file_count=job.entry_count,
            comment_chars=0,
            truncated=False,
            delivery_status=DeliveryStatus.NOT_ATTEMPTED.value,
            error_code="WEBHOOK_TIMEOUT",
            reason=reason,
        )

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._execute(job, self._timeout)
            except Exception:
                self._logger.exception("Webhook worker 执行异常")
            finally:
                self._queue.task_done()

    def _execute(self, job: ReviewJob, timeout: float | None) -> DeliveryRecord:
        budget = self._timeout if timeout is None else timeout
        started = self._clock()
        if budget <= 0:
            return self._timeout_record(job, "检查队列等待超时")
        acquired = self._semaphore.acquire(timeout=budget)
        if not acquired:
            raise QueueFullError("当前没有可用的检查并发名额")
        future = self._executor.submit(self._handler, job)
        released = False

        def release(_future: object) -> None:
            nonlocal released
            if not released:
                released = True
                self._semaphore.release()

        future.add_done_callback(release)
        remaining = max(0.0, budget - (self._clock() - started))
        try:
            return future.result(timeout=remaining)
        except concurrent.futures.TimeoutError:
            return self._timeout_record(job, "检查超时，结果可能不完整")

    def run_now(self, job: ReviewJob, timeout: float | None = None) -> DeliveryRecord:
        self.start()
        return self._execute(job, timeout if timeout is not None else self._timeout)

    def depth(self) -> int:
        return self._queue.qsize()

    def shutdown(self, timeout: float | None = None) -> None:
        budget = 10.0 if timeout is None else timeout
        self._stop.set()
        for worker in self._workers:
            worker.join(timeout=budget)
        self._executor.shutdown(wait=False, cancel_futures=False)
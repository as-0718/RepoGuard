from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path


class LockTimeout(RuntimeError):
    pass


class RepoLockRegistry:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _key(self, repo_root: Path) -> str:
        return os.path.normcase(str(repo_root.resolve()))

    @contextlib.contextmanager
    def acquire(self, repo_root: Path, timeout: float = 5.0) -> Iterator[None]:
        key = self._key(repo_root)
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(timeout=timeout):
            raise LockTimeout("仓库写操作排队超时")
        try:
            yield
        finally:
            lock.release()


_REGISTRY = RepoLockRegistry()


def registry() -> RepoLockRegistry:
    return _REGISTRY
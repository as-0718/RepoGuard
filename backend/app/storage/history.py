from __future__ import annotations

import datetime as _dt
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .db import connect

LOGGER = logging.getLogger("repoguard.storage.history")

_SNAPSHOT_COLUMNS = (
    "id",
    "repo_label",
    "repo_key",
    "scanned_at",
    "duration_ms",
    "files_count",
    "issue_count",
    "must_fix_count",
    "suggestion_count",
    "zombie_count",
    "undetermined_count",
    "status",
    "created_at",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def record_snapshot(
    db_path: Path | str,
    *,
    repo_label: str,
    repo_key: str,
    scanned_at: str,
    duration_ms: int,
    files_count: int,
    issue_count: int,
    must_fix_count: int,
    suggestion_count: int,
    zombie_count: int,
    undetermined_count: int,
    status: str,
    issues: Iterable[Any],
) -> int | None:
    """写入一条巡检快照及其问题明细，返回快照 ID；失败返回 None，不抛出异常。"""
    try:
        issue_rows = [
            (
                getattr(issue, "file_path", ""),
                getattr(issue, "line_no", None),
                getattr(issue, "rule_id", ""),
                getattr(issue, "source_module", ""),
                getattr(issue, "risk_level", ""),
                getattr(issue, "message", ""),
                getattr(issue, "suggestion", ""),
            )
            for issue in issues
        ]
        with connect(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO snapshots
                    (repo_label, repo_key, scanned_at, duration_ms, files_count,
                     issue_count, must_fix_count, suggestion_count, zombie_count,
                     undetermined_count, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo_label,
                    repo_key,
                    scanned_at,
                    int(duration_ms or 0),
                    int(files_count or 0),
                    int(issue_count or 0),
                    int(must_fix_count or 0),
                    int(suggestion_count or 0),
                    int(zombie_count or 0),
                    int(undetermined_count or 0),
                    status or "",
                    _now_iso(),
                ),
            )
            snapshot_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO issues
                    (snapshot_id, file_path, line_no, rule_id, source_module,
                     risk_level, message, suggestion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(snapshot_id, *row) for row in issue_rows],
            )
            conn.commit()
        return snapshot_id
    except Exception:
        LOGGER.exception("写入巡检快照失败")
        return None


def list_snapshots(
    db_path: Path | str,
    *,
    repo_key: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """返回最近的快照概要（按时间倒序）；查询失败返回空列表。"""
    limit = max(1, min(int(limit), 200))
    columns = ", ".join(_SNAPSHOT_COLUMNS)
    try:
        with connect(db_path) as conn:
            if repo_key:
                rows = conn.execute(
                    f"SELECT {columns} FROM snapshots WHERE repo_key = ? ORDER BY id DESC LIMIT ?",
                    (repo_key, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {columns} FROM snapshots ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        LOGGER.exception("查询历史快照失败")
        return []


def count_snapshots(db_path: Path | str, *, repo_key: str | None = None) -> int:
    """统计巡检快照总数（不受 limit 影响）；查询失败返回 0，不抛出异常。"""
    try:
        with connect(db_path) as conn:
            if repo_key:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM snapshots WHERE repo_key = ?",
                    (repo_key,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
        return int(row["n"] or 0)
    except Exception:
        LOGGER.exception("查询快照计数失败")
        return 0


def get_snapshot_with_issues(db_path: Path | str, snapshot_id: int) -> dict[str, Any] | None:
    """返回单条快照及其问题明细；不存在或失败返回 None。"""
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                f"SELECT {', '.join(_SNAPSHOT_COLUMNS)} FROM snapshots WHERE id = ?",
                (int(snapshot_id),),
            ).fetchone()
            if row is None:
                return None
            snapshot = dict(row)
            issue_rows = conn.execute(
                """
                SELECT file_path, line_no, rule_id, source_module, risk_level,
                       message, suggestion
                FROM issues
                WHERE snapshot_id = ?
                ORDER BY id
                """,
                (int(snapshot_id),),
            ).fetchall()
            snapshot["issues"] = [dict(item) for item in issue_rows]
        return snapshot
    except Exception:
        LOGGER.exception("查询快照详情失败")
        return None


def db_available(db_path: Path | str) -> bool:
    """探测数据库是否可连接（健康检查用）。"""
    try:
        with connect(db_path) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        LOGGER.exception("数据库连接探测失败")
        return False


_FIX_EVENT_COLUMNS = (
    "id",
    "created_at",
    "repo_label",
    "action",
    "result",
    "applied_count",
    "skipped_count",
    "restored_count",
    "failed_count",
    "files",
    "duration_ms",
    "request_id",
)


def record_fix_event(
    db_path: Path | str,
    *,
    repo_label: str,
    action: str,
    result: str,
    applied_count: int = 0,
    skipped_count: int = 0,
    restored_count: int = 0,
    failed_count: int = 0,
    files: Iterable[dict[str, str]] | Iterable[str] | None = None,
    duration_ms: int = 0,
    request_id: str = "",
) -> int | None:
    """写入一条修复/回滚事件，返回事件 ID；失败返回 None，不抛出异常。"""
    try:
        files_json = json.dumps(list(files or []), ensure_ascii=False)
        with connect(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO fix_events
                    (created_at, repo_label, action, result, applied_count,
                     skipped_count, restored_count, failed_count, files,
                     duration_ms, request_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    repo_label or "",
                    action or "",
                    result or "",
                    int(applied_count or 0),
                    int(skipped_count or 0),
                    int(restored_count or 0),
                    int(failed_count or 0),
                    files_json,
                    int(duration_ms or 0),
                    request_id or "",
                ),
            )
            conn.commit()
        return int(cur.lastrowid)
    except Exception:
        LOGGER.exception("写入修复记录失败")
        return None


def list_fix_events(
    db_path: Path | str,
    *,
    repo_label: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """返回最近的修复事件（按时间倒序）；查询失败返回空列表。"""
    limit = max(1, min(int(limit), 200))
    columns = ", ".join(_FIX_EVENT_COLUMNS)
    try:
        with connect(db_path) as conn:
            if repo_label:
                rows = conn.execute(
                    f"SELECT {columns} FROM fix_events WHERE repo_label = ? ORDER BY id DESC LIMIT ?",
                    (repo_label, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {columns} FROM fix_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            events = [dict(row) for row in rows]
        for event in events:
            try:
                event["files"] = json.loads(event.get("files") or "[]")
            except Exception:
                event["files"] = []
        return events
    except Exception:
        LOGGER.exception("查询修复记录失败")
        return []

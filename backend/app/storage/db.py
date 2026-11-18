from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

LOGGER = logging.getLogger("repoguard.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_label TEXT NOT NULL,
    repo_key TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    files_count INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    must_fix_count INTEGER NOT NULL DEFAULT 0,
    suggestion_count INTEGER NOT NULL DEFAULT 0,
    zombie_count INTEGER NOT NULL DEFAULT 0,
    undetermined_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL DEFAULT '',
    line_no INTEGER,
    rule_id TEXT NOT NULL DEFAULT '',
    source_module TEXT NOT NULL DEFAULT '',
    risk_level TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    suggestion TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_issues_snapshot ON issues(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_repo_time ON snapshots(repo_key, scanned_at);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """打开本地 SQLite 连接，开启外键约束并使用字典行。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str) -> None:
    """建表（幂等）。表已存在时不改动结构。"""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()

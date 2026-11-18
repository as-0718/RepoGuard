from __future__ import annotations

import datetime
import json
import logging
from typing import Any

LOGGER = logging.getLogger("repoguard.fixer")


def _clean_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in files:
        row = dict(item)
        for key in ("old_line", "new_line"):
            value = row.get(key)
            if isinstance(value, str):
                row[key] = value[:200]
        cleaned.append(row)
    return cleaned


def audit(
    action: str,
    *,
    request_id: str,
    repo_label: str,
    files: list[dict[str, Any]],
    result: str,
    duration_ms: int,
) -> None:
    record = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "request_id": request_id,
        "repo_label": repo_label,
        "action": action,
        "files": _clean_files(files),
        "result": result,
        "duration_ms": duration_ms,
    }
    LOGGER.info(json.dumps(record, ensure_ascii=False))
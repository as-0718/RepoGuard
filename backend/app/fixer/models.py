from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Patch:
    patch_id: str
    file_path: str
    line_no: int
    rule_id: str
    fixable: bool
    old_line: str
    new_line: str
    diff: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PatchDraft:
    old_line: str
    new_line: str


@dataclass(frozen=True, slots=True)
class Selection:
    file_path: str
    line_no: int
    rule_id: str
    old_line: str


@dataclass(frozen=True, slots=True)
class BackupRecord:
    file_path: str
    backup_path: str
    captured_at: str
    after_sha256: str


@dataclass(frozen=True, slots=True)
class ApplyResult:
    repo: str
    backup_id: str
    applied: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    backups: list[BackupRecord]


@dataclass(frozen=True, slots=True)
class RollbackResult:
    repo: str
    restored: list[dict[str, Any]]
    failed: list[dict[str, Any]]


def to_dict(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_dict(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Path):
        raise TypeError("Path 不允许进入响应")
    if isinstance(value, Mapping):
        return {str(key): to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_dict(item) for item in value]
    return value
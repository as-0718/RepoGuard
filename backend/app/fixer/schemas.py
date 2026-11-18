from __future__ import annotations

from typing import Literal

import pydantic


class IssueInput(pydantic.BaseModel):
    file_path: str = pydantic.Field(min_length=1, max_length=1024)
    line_no: int = pydantic.Field(ge=1)
    rule_id: str = pydantic.Field(min_length=1, max_length=32)
    excerpt: str | None = pydantic.Field(default=None, max_length=200)
    model_config = pydantic.ConfigDict(extra="ignore")


class SelectionInput(pydantic.BaseModel):
    file_path: str = pydantic.Field(min_length=1, max_length=1024)
    line_no: int = pydantic.Field(ge=1)
    rule_id: str = pydantic.Field(min_length=1, max_length=32)
    old_line: str = pydantic.Field(max_length=4000)
    model_config = pydantic.ConfigDict(extra="ignore")


class BackupInput(pydantic.BaseModel):
    file_path: str = pydantic.Field(min_length=1, max_length=1024)
    backup_path: str = pydantic.Field(min_length=1, max_length=1024)
    after_sha256: str | None = pydantic.Field(default=None, max_length=64)
    model_config = pydantic.ConfigDict(extra="ignore")


class PreviewRequest(pydantic.BaseModel):
    repo: str = pydantic.Field(min_length=1, max_length=512)
    issues: list[IssueInput] = pydantic.Field(min_length=1, max_length=200)
    strict: bool = False
    model_config = pydantic.ConfigDict(extra="ignore")


class ApplyRequest(pydantic.BaseModel):
    repo: str = pydantic.Field(min_length=1, max_length=512)
    backup_dir: str = pydantic.Field(min_length=1, max_length=1024)
    on_stale: Literal["skip", "reject"] = "skip"
    strict: bool = False
    selections: list[SelectionInput] = pydantic.Field(min_length=1, max_length=200)
    model_config = pydantic.ConfigDict(extra="ignore")


class RollbackRequest(pydantic.BaseModel):
    repo: str = pydantic.Field(min_length=1, max_length=512)
    backup_dir: str = pydantic.Field(min_length=1, max_length=1024)
    backup_id: str = pydantic.Field(min_length=1, max_length=64)
    force: bool = False
    strict: bool = False
    backups: list[BackupInput] = pydantic.Field(min_length=1, max_length=200)
    model_config = pydantic.ConfigDict(extra="ignore")
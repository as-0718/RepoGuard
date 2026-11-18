from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from . import audit, backup, locks, patches, paths
from .errors import (
    FIXER_BACKUP_DIR_FORBIDDEN,
    FIXER_BACKUP_PATH_FORBIDDEN,
    FIXER_FILE_UNDECODABLE,
    FIXER_INVALID_SELECTION,
    FIXER_IO_ERROR,
    FIXER_ROLLBACK_CONFLICT,
    FIXER_STALE_PATCH,
    raise_fixer,
)
from .models import ApplyResult, BackupRecord, Patch, RollbackResult, to_dict
from .paths import SymlinkTargetError
from .schemas import BackupInput, IssueInput, SelectionInput

MAX_SELECTIONS = 200
STALE_REASON = "文件内容已变化，补丁已过期"


def preview(repo_root: Path, issues: list[IssueInput], *, strict: bool) -> dict[str, object]:
    label = paths.repo_label(repo_root)
    result: list[dict[str, object]] = []
    undecodable = False
    for issue in issues:
        patch = patches.build_patch(repo_root, issue, label=label)
        if not patch.fixable and patch.reason == patches.REASON_UNDECODABLE:
            undecodable = True
        result.append(to_dict(patch))  # type: ignore[arg-type]
    if strict and undecodable:
        raise_fixer(FIXER_FILE_UNDECODABLE, 422, "存在无法按 UTF-8 解码的文件")
    return {"repo": label, "patches": result}


def _selection_key(selection: SelectionInput) -> tuple[str, int, str, str]:
    return (selection.file_path, selection.line_no, selection.rule_id, selection.old_line)


def _skipped(selection: SelectionInput, reason: str) -> dict[str, object]:
    return {"file_path": selection.file_path.replace("\\", "/"), "rule_id": selection.rule_id, "reason": reason}


def apply(
    repo_root: Path,
    backup_dir: Path,
    selections: list[SelectionInput],
    *,
    on_stale: str,
    strict: bool,
    request_id: str,
) -> dict[str, object]:
    started = time.perf_counter()
    label = paths.repo_label(repo_root)
    if not selections:
        raise_fixer(FIXER_INVALID_SELECTION, 400, "未选择任何补丁")
    if len(selections) > MAX_SELECTIONS:
        raise_fixer(FIXER_INVALID_SELECTION, 400, "单次选择的补丁过多")
    seen: set[tuple[str, int, str, str]] = set()
    for selection in selections:
        key = _selection_key(selection)
        if key in seen:
            raise_fixer(FIXER_INVALID_SELECTION, 400, "存在重复的补丁定位")
        seen.add(key)
        if selection.rule_id != "link-005":
            raise_fixer(FIXER_INVALID_SELECTION, 400, "只允许处理 link-005")

    rebuilt: list[tuple[SelectionInput, Patch]] = []
    skipped: list[dict[str, object]] = []
    stale: list[SelectionInput] = []
    undecodable: list[SelectionInput] = []

    for selection in selections:
        issue = IssueInput(
            file_path=selection.file_path,
            line_no=selection.line_no,
            rule_id=selection.rule_id,
            excerpt=None,
        )
        patch = patches.build_patch(repo_root, issue, label=label)
        if not patch.fixable:
            if patch.reason in (patches.REASON_UNDECODABLE, patches.REASON_UNREADABLE, patches.REASON_SYMLINK):
                if patch.reason == patches.REASON_UNDECODABLE:
                    undecodable.append(selection)
                skipped.append(_skipped(selection, patch.reason or "不可修复"))
                continue
            raise_fixer(FIXER_INVALID_SELECTION, 400, patch.reason or "补丁定位失败")
        if patch.old_line != selection.old_line:
            stale.append(selection)
            skipped.append(_skipped(selection, STALE_REASON))
            continue
        rebuilt.append((selection, patch))

    if strict and undecodable:
        raise_fixer(FIXER_FILE_UNDECODABLE, 422, "存在无法按 UTF-8 解码的文件")
    if on_stale == "reject" and stale:
        raise_fixer(FIXER_STALE_PATCH, 409, "存在已过期的补丁，整请求未写入")

    if not rebuilt:
        result = ApplyResult(repo=label, backup_id="", applied=[], skipped=skipped, backups=[])
        audit.audit(
            "apply",
            request_id=request_id,
            repo_label=label,
            files=[],
            result=f"applied=0 skipped={len(skipped)}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return to_dict(result)  # type: ignore[return-value]

    try:
        with locks.registry().acquire(repo_root, timeout=5.0):
            result = _apply_locked(
                repo_root,
                backup_dir,
                label,
                rebuilt,
                skipped,
                request_id,
                started,
            )
    except locks.LockTimeout:
        raise_fixer(FIXER_IO_ERROR, 503, "当前仓库有写操作正在进行，请稍后重试")
    return to_dict(result)  # type: ignore[return-value]


def _apply_locked(
    repo_root: Path,
    backup_dir: Path,
    label: str,
    rebuilt: list[tuple[SelectionInput, Patch]],
    skipped: list[dict[str, object]],
    request_id: str,
    started: float,
) -> ApplyResult:
    backup_id = backup.new_backup_id(backup_dir)
    backup_root = backup_dir / backup_id
    groups: dict[str, list[tuple[SelectionInput, Patch]]] = {}
    for selection, patch in rebuilt:
        groups.setdefault(patch.file_path, []).append((selection, patch))

    applied: list[dict[str, object]] = []
    backups: list[BackupRecord] = []
    audit_files: list[dict[str, object]] = []

    for file_path, group in groups.items():
        try:
            source = paths.resolve_file(repo_root, file_path)
        except SymlinkTargetError:
            for selection, _patch in group:
                skipped.append(_skipped(selection, patches.REASON_SYMLINK))
            continue
        try:
            data = source.read_bytes()
        except OSError:
            for selection, _patch in group:
                skipped.append(_skipped(selection, patches.REASON_UNREADABLE))
            continue
        try:
            text, encoding = patches.decode_text(data)
        except UnicodeDecodeError:
            for selection, _patch in group:
                skipped.append(_skipped(selection, patches.REASON_UNDECODABLE))
            continue
        newline = "\r\n" if "\r\n" in text else "\n"
        trailing = text.endswith("\n") or text.endswith("\r")
        lines = text.splitlines()
        valid: list[tuple[SelectionInput, Patch]] = []
        for selection, patch in sorted(group, key=lambda item: item[1].line_no):
            if patch.line_no < 1 or patch.line_no > len(lines) or lines[patch.line_no - 1] != patch.old_line:
                skipped.append(_skipped(selection, STALE_REASON))
                continue
            valid.append((selection, patch))
        if not valid:
            continue
        relative = f"{label}/{file_path}"
        try:
            record = backup.backup_file(backup_root, source, relative)
        except OSError:
            for selection, _patch in valid:
                skipped.append(_skipped(selection, "备份失败"))
            continue
        for _selection, patch in valid:
            lines[patch.line_no - 1] = patch.new_line
        new_text = newline.join(lines) + (newline if trailing else "")
        payload = new_text.encode(encoding)
        try:
            backup.atomic_write(source, payload)
        except OSError:
            for selection, _patch in valid:
                skipped.append(_skipped(selection, "写入失败"))
            continue
        after_sha256 = backup.sha256_bytes(payload)
        record = replace(record, after_sha256=after_sha256)
        backups.append(record)
        for _selection, patch in valid:
            applied.append(
                {
                    "patch_id": patch.patch_id,
                    "file_path": patch.file_path,
                    "line_no": patch.line_no,
                    "after_sha256": after_sha256,
                }
            )
            audit_files.append(
                {
                    "file_path": patch.file_path,
                    "rule_id": patch.rule_id,
                    "old_line": patch.old_line,
                    "new_line": patch.new_line,
                }
            )

    audit.audit(
        "apply",
        request_id=request_id,
        repo_label=label,
        files=audit_files,
        result=f"applied={len(applied)} skipped={len(skipped)}",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return ApplyResult(
        repo=label,
        backup_id=backup_id if applied else "",
        applied=applied,
        skipped=skipped,
        backups=backups,
    )


def rollback(
    repo_root: Path,
    backup_dir: Path,
    backup_id: str,
    backups: list[BackupInput],
    *,
    force: bool,
    strict: bool,
    request_id: str,
) -> dict[str, object]:
    started = time.perf_counter()
    label = paths.repo_label(repo_root)
    backup_root = paths.resolve_backup_path(backup_dir, backup_id)
    if not backup_root.is_dir():
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录不存在")

    prepared: list[tuple[BackupInput, Path, bytes]] = []
    restored: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    conflicts: list[str] = []
    audit_files: list[dict[str, object]] = []

    for item in backups:
        try:
            target = paths.resolve_file(repo_root, item.file_path)
        except SymlinkTargetError:
            failed.append({"file_path": item.file_path, "reason": patches.REASON_SYMLINK})
            continue
        source = paths.resolve_backup_path(backup_dir, item.backup_path)
        if not paths.is_within(source, backup_root):
            raise_fixer(FIXER_BACKUP_PATH_FORBIDDEN, 403, "备份路径越界")
        if not source.is_file():
            failed.append({"file_path": item.file_path, "reason": "备份原件缺失"})
            continue
        try:
            data = source.read_bytes()
        except OSError:
            failed.append({"file_path": item.file_path, "reason": "备份原件不可读"})
            continue
        if item.after_sha256:
            current = target.read_bytes() if target.exists() else b""
            if backup.sha256_bytes(current) != item.after_sha256:
                if force:
                    prepared.append((item, target, data))
                    continue
                if strict:
                    conflicts.append(item.file_path)
                failed.append({"file_path": item.file_path, "reason": "文件已被手工修改"})
                continue
        prepared.append((item, target, data))

    if strict and conflicts:
        raise_fixer(FIXER_ROLLBACK_CONFLICT, 409, "文件已被手工修改，拒绝覆盖")

    try:
        with locks.registry().acquire(repo_root, timeout=5.0):
            for item, target, data in prepared:
                try:
                    backup.atomic_write(target, data)
                    restored.append({"file_path": item.file_path})
                    audit_files.append({"file_path": item.file_path, "backup_path": item.backup_path})
                except OSError:
                    failed.append({"file_path": item.file_path, "reason": "回滚写入失败"})
    except locks.LockTimeout:
        raise_fixer(FIXER_IO_ERROR, 503, "当前仓库有写操作正在进行，请稍后重试")

    audit.audit(
        "rollback",
        request_id=request_id,
        repo_label=label,
        files=audit_files,
        result=f"restored={len(restored)} failed={len(failed)}",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return to_dict(RollbackResult(repo=label, restored=restored, failed=failed))  # type: ignore[return-value]
from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

from ..core.rules.link_check import DEFINITION_RE, INLINE_RE

from .models import Patch, PatchDraft
from .paths import SymlinkTargetError, resolve_file
from .schemas import IssueInput

REASON_NON_WHITELIST = "非白名单规则"
REASON_UNDECODABLE = "文件无法按 UTF-8 解码"
REASON_LOCATE = "定位不到 link-005 目标"
REASON_SYMLINK = "目标文件是符号链接"
REASON_UNREADABLE = "文件不可读"

_TITLE_RE = re.compile(r"^(.*?)(\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))\s*$", re.S)


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    return data.decode("utf-8"), "utf-8"


def _rewrite_inner(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None
    leading = raw[: len(raw) - len(raw.lstrip())]
    trailing = raw[len(raw.rstrip()) :]
    stripped = raw.strip()
    if stripped.startswith("<") and ">" in stripped:
        return None
    match = _TITLE_RE.match(stripped)
    if match:
        target = match.group(1).rstrip()
        title = match.group(2)
    else:
        target = stripped
        title = ""
    if " " not in target:
        return None
    return leading + target.replace(" ", "%20") + title + trailing


def build_line_patch(line: str, line_no: int, rule_id: str, file_path: str) -> PatchDraft | None:
    if rule_id != "link-005":
        return None
    new_line = line
    for match in reversed(list(INLINE_RE.finditer(line))):
        rewritten = _rewrite_inner(match.group(3))
        if rewritten is None:
            continue
        new_line = new_line[: match.start(3)] + rewritten + new_line[match.end(3) :]
    definition = DEFINITION_RE.match(new_line)
    if definition and definition.group(2):
        rewritten = _rewrite_inner(definition.group(2))
        if rewritten is not None:
            new_line = new_line[: definition.start(2)] + rewritten + new_line[definition.end(2) :]
    if new_line == line:
        return None
    return PatchDraft(old_line=line, new_line=new_line)


def _not_fixable(issue: IssueInput, reason: str) -> Patch:
    return Patch(
        patch_id="",
        file_path=issue.file_path.replace("\\", "/"),
        line_no=issue.line_no,
        rule_id=issue.rule_id,
        fixable=False,
        old_line="",
        new_line="",
        diff="",
        reason=reason,
    )


def build_patch(repo_root: Path, issue: IssueInput, *, label: str) -> Patch:
    if issue.rule_id != "link-005":
        return _not_fixable(issue, REASON_NON_WHITELIST)
    try:
        path = resolve_file(repo_root, issue.file_path)
    except SymlinkTargetError:
        return _not_fixable(issue, REASON_SYMLINK)
    try:
        data = path.read_bytes()
    except OSError:
        return _not_fixable(issue, REASON_UNREADABLE)
    try:
        text, _encoding = decode_text(data)
    except UnicodeDecodeError:
        return _not_fixable(issue, REASON_UNDECODABLE)
    lines = text.splitlines()
    if issue.line_no < 1 or issue.line_no > len(lines):
        return _not_fixable(issue, REASON_LOCATE)
    old_line = lines[issue.line_no - 1]
    draft = build_line_patch(old_line, issue.line_no, issue.rule_id, issue.file_path)
    if draft is None:
        return _not_fixable(issue, REASON_LOCATE)
    file_path = issue.file_path.replace("\\", "/")
    patch_id = hashlib.sha256(
        f"{label}|{file_path}|{issue.line_no}|link-005|{draft.old_line}|{draft.new_line}".encode("utf-8")
    ).hexdigest()[:16]
    diff = "\n".join(
        difflib.unified_diff(
            [draft.old_line],
            [draft.new_line],
            fromfile=f"{file_path}:{issue.line_no}",
            tofile=f"{file_path}:{issue.line_no}",
            lineterm="",
        )
    )
    return Patch(
        patch_id=patch_id,
        file_path=file_path,
        line_no=issue.line_no,
        rule_id="link-005",
        fixable=True,
        old_line=draft.old_line,
        new_line=draft.new_line,
        diff=diff,
        reason=None,
    )
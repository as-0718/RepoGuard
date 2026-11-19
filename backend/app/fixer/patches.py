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
REASON_LOCATE = "定位不到可修复内容"
REASON_SYMLINK = "目标文件是符号链接"
REASON_UNREADABLE = "文件不可读"

# 允许自动修复的规则白名单：仅限行内可机械改写、结果确定且可回滚的规则。
FIXABLE_RULES = {"link-005", "code-012", "code-010"}

_NONE_EQ_RE = re.compile(r"==\s*None")
_NONE_NE_RE = re.compile(r"!=\s*None")
_DEBUG_BREAK_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:breakpoint\s*\(|pdb\.set_trace\s*\()")

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


def _rewrite_none_compare(line: str) -> str | None:
    """code-012：把 == None / != None 等价改写为 is None / is not None。"""
    new_line = _NONE_EQ_RE.sub("is None", line)
    new_line = _NONE_NE_RE.sub("is not None", new_line)
    return None if new_line == line else new_line


def _comment_out_debug_break(line: str) -> str | None:
    """code-010：把调试断点整行注释化，保留缩进与原文，不删行以便回滚。"""
    if not _DEBUG_BREAK_RE.search(line):
        return None
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return None
    indent = line[: len(line) - len(stripped)]
    return f"{indent}# {stripped}  # 自动移除调试断点"


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


def _build_draft(rule_id: str, line: str, line_no: int, file_path: str) -> PatchDraft | None:
    if rule_id == "link-005":
        return build_line_patch(line, line_no, rule_id, file_path)
    if rule_id == "code-012":
        new_line = _rewrite_none_compare(line)
        return None if new_line is None else PatchDraft(old_line=line, new_line=new_line)
    if rule_id == "code-010":
        new_line = _comment_out_debug_break(line)
        return None if new_line is None else PatchDraft(old_line=line, new_line=new_line)
    return None


def build_patch(repo_root: Path, issue: IssueInput, *, label: str) -> Patch:
    if issue.rule_id not in FIXABLE_RULES:
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
    draft = _build_draft(issue.rule_id, old_line, issue.line_no, issue.file_path)
    if draft is None:
        return _not_fixable(issue, REASON_LOCATE)
    file_path = issue.file_path.replace("\\", "/")
    patch_id = hashlib.sha256(
        f"{label}|{file_path}|{issue.line_no}|{issue.rule_id}|{draft.old_line}|{draft.new_line}".encode("utf-8")
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
        rule_id=issue.rule_id,
        fixable=True,
        old_line=draft.old_line,
        new_line=draft.new_line,
        diff=diff,
        reason=None,
    )
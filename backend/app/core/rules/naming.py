from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

from .common.file_io import CheckContext
from .common.models import (
    ChangeEntry,
    ChangeStatus,
    IssueLevel,
    ModuleResult,
    make_finding,
    merge_findings,
)

if TYPE_CHECKING:
    from .common.config import RuleConfig

ILLEGAL_NAME_CHARS = set('<>:"|?*')
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
SOURCE_EXTENSIONS = {".c", ".h", ".py"}

_CHINESE_WORDS = (
    ("串口", "serial"),
    ("通信", "communication"),
    ("实验", "lab"),
    ("报告", "report"),
    ("指导", "guide"),
    ("笔记", "notes"),
    ("课程", "course"),
    ("数据", "data"),
    ("结构", "struct"),
    ("算法", "algorithm"),
    ("网络", "network"),
    ("测试", "test"),
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _is_under(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    segments = _segments(path)
    if not segments:
        return False
    return segments[0] == normalized or path.startswith(normalized + "/")


def is_test_file(path: str) -> bool:
    name = posixpath.basename(path).lower()
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "tests" in _segments(path)


def suggest_file_name(file_name: str) -> str:
    stem, extension = posixpath.splitext(file_name)
    text = stem
    for chinese, english in _CHINESE_WORDS:
        text = text.replace(chinese, f"_{english}_")
    text = _CJK_RE.sub("_cn_", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text.startswith("lab") and text.endswith("_lab"):
        text = text[:-4].rstrip("_")
    if not text:
        text = "renamed_file"
    return f"{text}{extension.lower()}"


def _has_style_issue(name: str) -> bool:
    if re.search(r"[A-Z]", name):
        return True
    if " " in name or "-" in name:
        return True
    if "__" in name:
        return True
    for char in name:
        if ord(char) > 127 and not _CJK_RE.match(char):
            return True
    return False


def check_naming(path: str, config: "RuleConfig") -> tuple:
    findings = []
    file_name = posixpath.basename(path)

    illegal = [char for char in file_name if char in ILLEGAL_NAME_CHARS or ord(char) < 0x20]
    if illegal or file_name.endswith("."):
        suggested = suggest_file_name(file_name)
        for char in ILLEGAL_NAME_CHARS | {chr(code) for code in range(0x20)}:
            suggested = suggested.replace(char, "_")
        suggested = re.sub(r"_+", "_", suggested)
        findings.append(
            make_finding(
                level=IssueLevel.MUST_FIX,
                file_path=path,
                message="文件名包含系统不允许的特殊字符或结尾点，提交后可能无法正常检出",
                suggestion=f"去掉非法字符，推荐命名为：{suggested}",
                rule_id="naming-001",
            )
        )

    if len(file_name) > 120:
        suggested = suggest_file_name(file_name)
        if len(suggested) > 60:
            suggested = suggested[:56] + suggested[-4:]
        findings.append(
            make_finding(
                level=IssueLevel.MUST_FIX,
                file_path=path,
                message=f"文件名长度为 {len(file_name)} 个字符，超过 120 字符上限",
                suggestion=f"缩短到 60 个字符以内，例如：{suggested}",
                rule_id="naming-002",
            )
        )

    if _has_chinese(file_name) or any(_has_chinese(segment) for segment in _segments(path)):
        suggested_name = suggest_file_name(file_name)
        target = posixpath.join(posixpath.dirname(path), suggested_name) if posixpath.dirname(path) else suggested_name
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=path,
                message="文件名或路径包含中文，跨平台工具链和自动化脚本可能不便处理",
                suggestion=f"建议改为英文或拼音加下划线，例如：{target}",
                rule_id="naming-004",
            )
        )
    elif _has_style_issue(file_name):
        suggested_name = suggest_file_name(file_name)
        target = posixpath.join(posixpath.dirname(path), suggested_name) if posixpath.dirname(path) else suggested_name
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=path,
                message="文件名风格不统一，推荐使用小写英文加下划线的形式",
                suggestion=f"推荐命名为：{target}",
                rule_id="naming-003",
            )
        )

    return tuple(findings)


def suggest_directory(path: str, config: "RuleConfig") -> str | None:
    extension = posixpath.splitext(path)[1].lower()
    if is_test_file(path):
        return "backend/tests/"
    key = extension.lstrip(".")
    allowed = config.directory_map.get(key)
    if not allowed:
        return None
    return allowed[0]


def check_directory(path: str, config: "RuleConfig") -> tuple:
    findings = []
    extension = posixpath.splitext(path)[1].lower()
    if not extension:
        return ()
    segments = _segments(path)
    file_name = posixpath.basename(path)

    hard_reason: str | None = None
    target_dir: str | None = None

    if is_test_file(path) and not _is_under(path, "backend/tests"):
        hard_reason = "测试文件没有放在 backend/tests/ 目录下"
        target_dir = "backend/tests/"
    elif extension in {".c", ".h", ".py"} and _is_under(path, "docs"):
        hard_reason = "源码文件被放在了 docs/ 文档目录下"
        target_dir = "lab/"
    elif extension == ".md" and segments and segments[0] in {"backend", "src", "lab"}:
        hard_reason = "文档文件被放在了代码目录下"
        target_dir = "docs/"

    if hard_reason is not None:
        target = f"{target_dir}{file_name}"
        findings.append(
            make_finding(
                level=IssueLevel.MUST_FIX,
                file_path=path,
                message=f"{hard_reason}，目录结构不符合学习仓库约定",
                suggestion=f"移动到推荐位置，例如：{target}",
                rule_id="naming-005",
            )
        )
        return tuple(findings)

    suggestion: str | None = None
    if extension in SOURCE_EXTENSIONS and len(segments) == 1:
        suggestion = f"lab/{file_name}"
    elif extension in IMAGE_EXTENSIONS and not (
        _is_under(path, "assets") or _is_under(path, "docs/assets")
    ):
        suggestion = f"assets/{file_name}"
    elif extension == ".md" and not _is_under(path, "docs"):
        name_lower = file_name.lower()
        if (
            re.search(r"lab\d+", name_lower)
            or "实验" in file_name
            or "报告" in file_name
            or "report" in name_lower
        ):
            suggestion = f"docs/{file_name}"

    if suggestion is not None:
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=path,
                message="文件所在目录与学习仓库的目录约定不一致",
                suggestion=f"建议移动到：{suggestion}",
                rule_id="naming-006",
            )
        )
    return tuple(findings)


def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult:
    findings = list(check_naming(entry.path, ctx.config))
    findings.extend(check_directory(entry.path, ctx.config))
    merged = merge_findings(
        findings,
        max_per_rule_per_file=ctx.config.max_findings_per_rule_per_file,
        module_label="命名与目录检查",
    )
    return ModuleResult(findings=tuple(merged[:4]))
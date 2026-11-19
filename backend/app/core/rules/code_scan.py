from __future__ import annotations

import ast
import re
import time
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

C_KEYWORDS = {
    "if", "for", "while", "switch", "return", "sizeof", "struct", "union",
    "enum", "typedef", "do", "else", "case", "goto", "defined",
}

FUNCTION_RE = re.compile(
    r"^\s*(?:(?:static|inline|extern|const|unsigned|signed|long|short|volatile)\s+)*"
    r"[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{?\s*$"
)


def detect_language(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith(".c") or lowered.endswith(".h"):
        return "c"
    return "none"


def build_code_view(text: str, language: str) -> str:
    chars = list(text)
    length = len(text)
    index = 0
    is_python = language == "python"

    while index < length:
        char = text[index]

        if is_python and char == "#":
            while index < length and text[index] != "\n":
                chars[index] = " "
                index += 1
            continue

        if not is_python and char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                chars[index] = " "
                index += 1
            continue

        if not is_python and char == "/" and index + 1 < length and text[index + 1] == "*":
            chars[index] = " "
            chars[index + 1] = " "
            index += 2
            while index < length:
                if text[index] == "*" and index + 1 < length and text[index + 1] == "/":
                    chars[index] = " "
                    chars[index + 1] = " "
                    index += 2
                    break
                if text[index] != "\n":
                    chars[index] = " "
                index += 1
            continue

        if is_python and (text.startswith('"""', index) or text.startswith("'''", index)):
            quote = text[index:index + 3]
            chars[index] = chars[index + 1] = chars[index + 2] = " "
            index += 3
            while index < length:
                if text.startswith(quote, index):
                    chars[index] = chars[index + 1] = chars[index + 2] = " "
                    index += 3
                    break
                if text[index] == "\\":
                    chars[index] = " "
                    if index + 1 < length and text[index + 1] != "\n":
                        chars[index + 1] = " "
                    index += 2
                    continue
                if text[index] != "\n":
                    chars[index] = " "
                index += 1
            continue

        if char in ("'", '"'):
            quote = char
            chars[index] = " "
            index += 1
            while index < length:
                if text[index] == "\\":
                    chars[index] = " "
                    if index + 1 < length and text[index + 1] != "\n":
                        chars[index + 1] = " "
                    index += 2
                    continue
                if text[index] == quote:
                    chars[index] = " "
                    index += 1
                    break
                if text[index] != "\n":
                    chars[index] = " "
                index += 1
            continue

        index += 1
    return "".join(chars)


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _excerpt(text: str, line_no: int) -> str | None:
    lines = text.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()[:60] or None
    return None


def _has_comment_above(source_lines: list[str], line_no: int) -> bool:
    index = line_no - 2
    while index >= 0 and not source_lines[index].strip():
        index -= 1
    if index < 0:
        return False
    stripped = source_lines[index].strip()
    return stripped.startswith("//") or stripped.startswith("*") or stripped.endswith("*/") or stripped.startswith("/*")


_COMMENT_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")


def _scan_comment_markers(text: str, file_path: str, language: str) -> list:
    """扫描注释中遗留的 TODO/FIXME/HACK/XXX 标记（建议级）。"""
    findings = []
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if language == "python":
            is_comment = stripped.startswith("#")
        else:
            is_comment = (
                stripped.startswith("//")
                or stripped.startswith("/*")
                or stripped.endswith("*/")
                or stripped.startswith("*")
            )
        if not is_comment:
            continue
        match = _COMMENT_MARKER_RE.search(stripped)
        if not match:
            continue
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=file_path,
                message=f"注释中留有 {match.group(1)} 遗留标记，需确认是否已处理",
                suggestion="提交前确认该事项已完成；已完成则删除标记，未完成请补充处理计划或工单",
                rule_id="code-009",
                line_no=index,
                excerpt=stripped[:60] or None,
            )
        )
    return findings


_MUTABLE_LITERAL_NODES = (ast.List, ast.Dict, ast.Set)


def _scan_python_bug_patterns(tree: ast.AST, file_path: str) -> list:
    """扫描可由 AST 静态判定的常见 bug 写法（建议级）。"""
    findings: list = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        defaults = list(node.args.defaults)
        defaults.extend(d for d in node.args.kw_defaults if d is not None)
        mutable_defaults = [d for d in defaults if isinstance(d, _MUTABLE_LITERAL_NODES)]
        if mutable_defaults:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message=f"函数 {node.name} 用可变对象作默认参数，多次调用会共享同一对象",
                    suggestion="① 默认值改为 None；② 函数体首行用 if arg is None: arg = [] 按需初始化",
                    rule_id="code-011",
                    line_no=node.lineno,
                )
            )

        body = list(node.body)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body = body[1:]
        real_body = [
            stmt
            for stmt in body
            if not (
                isinstance(stmt, ast.Pass)
                or (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is Ellipsis
                )
            )
        ]
        if body and not real_body:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message=f"函数 {node.name} 函数体为空（仅 pass 或 ...），缺少实际实现",
                    suggestion="① 补全函数实现；② 未完成时抛出 NotImplementedError 并注释原因，避免被误调用",
                    rule_id="code-013",
                    line_no=node.lineno,
                )
            )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        has_eq_op = any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        has_none = any(isinstance(c, ast.Constant) and c.value is None for c in node.comparators)
        if has_eq_op and has_none:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message="用 == None 或 != None 比较身份，应改用 is / is not",
                    suggestion="将 == None 改为 is None，!= None 改为 is not None，身份比较更稳妥",
                    rule_id="code-012",
                    line_no=node.lineno,
                )
            )

    return findings


def _apply_patterns(
    code_view: str,
    source_text: str,
    language: str,
    config: "RuleConfig",
    file_path: str,
) -> list:
    findings = []
    seen: set[tuple[str, int]] = set()
    for spec in config.hard_dangerous_patterns + config.suspicious_patterns:
        if spec.language not in (language, "any"):
            continue
        for match in spec.pattern.finditer(code_view):
            line_no = _line_of(code_view, match.start())
            key = (spec.rule_id, line_no)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                make_finding(
                    level=spec.level,
                    file_path=file_path,
                    message=spec.message,
                    suggestion=spec.suggestion,
                    rule_id=spec.rule_id,
                    line_no=line_no,
                    excerpt=_excerpt(source_text, line_no),
                )
            )
    return findings


def _python_magic_number(source_text: str, node: ast.AST) -> bool:
    numbers = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) and not isinstance(child.value, bool):
            numbers.append(child.value)
    if any(abs(value) >= 1000 for value in numbers):
        return True
    counts: dict[float, int] = {}
    for value in numbers:
        if value in (0, 1, 2):
            continue
        counts[value] = counts.get(value, 0) + 1
    return any(count >= 3 for count in counts.values())


def scan_python_source(
    text: str,
    file_path: str,
    config: "RuleConfig",
    *,
    downgrade_level: bool = False,
) -> tuple:
    findings: list = []
    source_lines = text.splitlines()

    try:
        tree = ast.parse(text)
        parse_ok = True
    except SyntaxError:
        tree = None
        parse_ok = False

    if parse_ok and tree is not None:
        if ast.get_docstring(tree) is None:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message="模块开头缺少说明注释，读者不易了解文件用途",
                    suggestion='在文件第一行补充模块说明，例如："""串口数据收发示例"""',
                    rule_id="code-001",
                )
            )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if ast.get_docstring(node) is not None:
                continue
            name = node.name
            line_no = node.lineno
            has_comment = _has_comment_above(source_lines, line_no)
            is_public = not name.startswith("_")
            body_lines = (getattr(node, "end_lineno", line_no) or line_no) - line_no + 1
            if is_public:
                findings.append(
                    make_finding(
                        level=IssueLevel.MUST_FIX,
                        file_path=file_path,
                        message=f"公开函数 {name} 缺少说明注释，影响他人阅读和复用",
                        suggestion=f'在函数体首行补充文档字符串，例如："""{name}：说明用途、参数与返回值"""',
                        rule_id="code-002",
                        line_no=line_no,
                    )
                )
            elif not has_comment and body_lines <= 10:
                findings.append(
                    make_finding(
                        level=IssueLevel.SUGGESTION,
                        file_path=file_path,
                        message=f"内部函数 {name} 较短但缺少用途说明，可读性一般",
                        suggestion=f"在 def {name} 上方补一行注释，说明该辅助函数的用途",
                        rule_id="code-003",
                        line_no=line_no,
                    )
                )
            if _python_magic_number(text, node):
                findings.append(
                    make_finding(
                        level=IssueLevel.SUGGESTION,
                        file_path=file_path,
                        message=f"函数 {name} 中存在魔法数字，含义不够直观",
                        suggestion="把重复出现或较长的数字提取为有名字的常量，便于理解",
                        rule_id="code-007",
                        line_no=line_no,
                    )
                )
        findings.extend(_scan_python_bug_patterns(tree, file_path))

    findings.extend(_scan_comment_markers(text, file_path, "python"))
    code_view = build_code_view(text, "python")
    findings.extend(_apply_patterns(code_view, text, "python", config, file_path))

    if downgrade_level:
        findings = [
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=item.file_path,
                message=item.message,
                suggestion=item.suggestion,
                rule_id=item.rule_id,
                line_no=item.line_no,
                excerpt=item.excerpt,
            )
            if item.level is IssueLevel.MUST_FIX
            else item
            for item in findings
        ]
    return tuple(findings)


def _find_function_end(lines: list[str], start: int) -> int | None:
    depth = 0
    seen_open = False
    for index in range(start, min(len(lines), start + 400)):
        for char in lines[index]:
            if char == "{":
                depth += 1
                seen_open = True
            elif char == "}":
                depth -= 1
                if seen_open and depth == 0:
                    return index
    return None


def scan_c_source(
    text: str,
    file_path: str,
    config: "RuleConfig",
    *,
    downgrade_level: bool = False,
) -> tuple:
    findings: list = []
    text = text.lstrip("\ufeff")
    lines = text.splitlines()

    header_ok = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        header_ok = stripped.startswith("//") or stripped.startswith("/*")
        break
    if not header_ok:
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=file_path,
                message="C 文件开头缺少用途说明注释，读者不易了解文件功能",
                suggestion="在文件开头补一行块注释，例如：/* 本文件：串口数据收发示例 */",
                rule_id="code-001",
            )
        )

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            index += 1
            continue
        match = FUNCTION_RE.match(line)
        if not match:
            index += 1
            continue
        name = match.group(1)
        if name in C_KEYWORDS:
            index += 1
            continue
        open_index = index
        if "{" not in line:
            open_index = -1
            for probe in range(index + 1, min(len(lines), index + 4)):
                if "{" in lines[probe]:
                    open_index = probe
                    break
            if open_index < 0:
                index += 1
                continue
        end_index = _find_function_end(lines, open_index)
        if end_index is None:
            index += 1
            continue
        is_static = "static" in line
        line_no = index + 1
        has_comment = _has_comment_above(lines, line_no)
        body_lines = end_index - index + 1
        if name == "main" or not is_static:
            if not has_comment:
                findings.append(
                    make_finding(
                        level=IssueLevel.MUST_FIX,
                        file_path=file_path,
                        message=f"函数 {name} 缺少紧邻注释，调用者不易了解参数与用途",
                        suggestion=f"在函数定义上方补一行注释，例如：/* {name}：说明用途、参数与返回值 */",
                        rule_id="code-002",
                        line_no=line_no,
                    )
                )
        elif not has_comment and body_lines <= 10:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message=f"静态函数 {name} 较短但缺少用途说明，可读性一般",
                    suggestion=f"在函数定义上方补一行注释，说明 {name} 的用途",
                    rule_id="code-003",
                    line_no=line_no,
                )
            )
        numbers = re.findall(r"\b\d{4,}\b", "\n".join(lines[index:end_index + 1]))
        if numbers:
            findings.append(
                make_finding(
                    level=IssueLevel.SUGGESTION,
                    file_path=file_path,
                    message=f"函数 {name} 中存在较长数字，建议提取为具名常量",
                    suggestion="把含义不明的数字提取为常量或宏，并补充单位说明",
                    rule_id="code-007",
                    line_no=line_no,
                )
            )
        index = end_index + 1

    findings.extend(_scan_comment_markers(text, file_path, "c"))
    code_view = build_code_view(text, "c")
    findings.extend(_apply_patterns(code_view, text, "c", config, file_path))

    if downgrade_level:
        findings = [
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=item.file_path,
                message=item.message,
                suggestion=item.suggestion,
                rule_id=item.rule_id,
                line_no=item.line_no,
                excerpt=item.excerpt,
            )
            if item.level is IssueLevel.MUST_FIX
            else item
            for item in findings
        ]
    return tuple(findings)


def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult:
    if entry.status is ChangeStatus.DELETE:
        return ModuleResult()
    language = detect_language(entry.path)
    if language == "none":
        return ModuleResult()

    snapshot = ctx.snapshot(entry.path)
    if snapshot.is_binary:
        return ModuleResult(skip_reason="文件内容无法解码，已跳过代码检查")

    if snapshot.size > int(ctx.config.code_scan_max_mb * 1024 * 1024):
        finding = make_finding(
            level=IssueLevel.SUGGESTION,
            file_path=entry.path,
            message="文件体积过大，已跳过代码内容检查，建议拆分后再提交",
            suggestion="将大文件拆分为多个小文件，或把生成物移出学习仓库",
            rule_id="code-008",
        )
        return ModuleResult(findings=(finding,))

    text_result = snapshot.text()
    if text_result.text is None:
        return ModuleResult(skip_reason="文件内容无法解码，已跳过代码检查")

    started = time.perf_counter()
    downgrade = entry.path.lower().endswith(".h")
    if language == "python":
        findings = scan_python_source(text_result.text, entry.path, ctx.config, downgrade_level=downgrade)
    else:
        findings = scan_c_source(text_result.text, entry.path, ctx.config, downgrade_level=downgrade)

    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > ctx.config.per_file_budget_ms:
        findings = findings + (
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=entry.path,
                message="文件检查耗时超过预算，部分内容可能未完整扫描",
                suggestion="建议拆分文件，或仅对改动较小的文件执行检查",
                rule_id="code-008",
            ),
        )

    merged = merge_findings(
        findings,
        max_per_rule_per_file=ctx.config.max_findings_per_rule_per_file,
        module_label="代码检查",
    )
    merged = tuple(sorted(merged, key=lambda item: (item.line_no is None, item.line_no or 0, item.rule_id)))
    return ModuleResult(findings=merged)
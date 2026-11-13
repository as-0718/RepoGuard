from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Sequence

MAX_RAW_LENGTH = 500
MIN_MESSAGE_LENGTH = 8
MAX_MESSAGE_LENGTH = 200
MAX_SUGGESTION_LENGTH = 300
MAX_EXCERPT_LENGTH = 60


class ChangeStatus(Enum):
    ADD = "A"
    MODIFY = "M"
    DELETE = "D"

    @classmethod
    def from_value(cls, value: str) -> "ChangeStatus":
        text = value.strip().upper()
        for item in cls:
            if item.value == text:
                return item
        raise ValueError(f"未知状态：{value}")


class IssueLevel(Enum):
    MUST_FIX = "必须修改"
    SUGGESTION = "优化建议"


class ReportStatus(Enum):
    OK = "正常"
    PARTIAL_DEGRADED = "部分降级"
    INPUT_ERROR = "输入错误"


class ExitCode(IntEnum):
    OK = 0
    MUST_FIX = 1
    INPUT_ERROR = 2
    EXECUTION_ERROR = 3


@dataclass(frozen=True, slots=True)
class ChangeEntry:
    status: ChangeStatus
    path: str
    line_no: int
    raw: str | None = None
    duplicate_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.status, ChangeStatus):
            raise ValueError("变更状态必须是 ChangeStatus 枚举值")
        if not self.path:
            raise ValueError("文件路径不能为空")
        if self.line_no < 1:
            raise ValueError("行号必须大于等于 1")
        if self.duplicate_count < 1:
            raise ValueError("重复计数必须大于等于 1")
        if self.raw is not None and len(self.raw) > MAX_RAW_LENGTH:
            object.__setattr__(self, "raw", self.raw[:MAX_RAW_LENGTH])

    @property
    def has_illegal_path(self) -> bool:
        normalized = self.path.replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("//"):
            return True
        if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
            return True
        return any(segment == ".." for segment in normalized.split("/"))


@dataclass(frozen=True, slots=True)
class UnparsedLine:
    line_no: int
    raw: str
    reason: str


@dataclass(frozen=True, slots=True)
class Finding:
    level: IssueLevel
    file_path: str
    message: str
    suggestion: str
    rule_id: str
    line_no: int | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.level, IssueLevel):
            raise ValueError("问题级别必须是 IssueLevel 枚举值")
        if not self.file_path:
            raise ValueError("问题必须包含文件路径")
        if len(self.message) < MIN_MESSAGE_LENGTH:
            raise ValueError("问题描述不得少于 8 个字符")
        if len(self.message) > MAX_MESSAGE_LENGTH:
            object.__setattr__(self, "message", self.message[:MAX_MESSAGE_LENGTH])
        if len(self.suggestion) > MAX_SUGGESTION_LENGTH:
            object.__setattr__(self, "suggestion", self.suggestion[:MAX_SUGGESTION_LENGTH])
        if self.line_no is not None and self.line_no < 1:
            raise ValueError("问题行号必须大于等于 1")
        if self.excerpt is not None and len(self.excerpt) > MAX_EXCERPT_LENGTH:
            object.__setattr__(self, "excerpt", self.excerpt[:MAX_EXCERPT_LENGTH])


@dataclass(frozen=True, slots=True)
class FileGroup:
    file_path: str
    status: ChangeStatus
    findings: tuple[Finding, ...] = ()
    skip_reason: str | None = None
    duplicate_count: int = 1


@dataclass(frozen=True, slots=True)
class CheckSummary:
    entry_count: int
    issue_count: int
    must_fix_count: int
    suggestion_count: int
    skipped_file_count: int
    degraded_module_count: int
    unparsed_line_count: int


@dataclass(frozen=True, slots=True)
class DegradedModule:
    module: str
    reason: str


@dataclass(frozen=True, slots=True)
class CheckReport:
    status: ReportStatus
    summary: CheckSummary
    files: tuple[FileGroup, ...] = ()
    unparsed_lines: tuple[UnparsedLine, ...] = ()
    degraded_modules: tuple[DegradedModule, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestParseResult:
    entries: tuple[ChangeEntry, ...] = ()
    unparsed_lines: tuple[UnparsedLine, ...] = ()


@dataclass(frozen=True, slots=True)
class ModuleResult:
    findings: tuple[Finding, ...] = ()
    skip_reason: str | None = None


def make_finding(
    *,
    level: IssueLevel,
    file_path: str,
    message: str,
    suggestion: str,
    rule_id: str,
    line_no: int | None = None,
    excerpt: str | None = None,
) -> Finding:
    return Finding(
        level=level,
        file_path=file_path,
        message=message,
        suggestion=suggestion,
        rule_id=rule_id,
        line_no=line_no,
        excerpt=excerpt,
    )


def merge_findings(
    findings: Sequence[Finding],
    *,
    max_per_rule_per_file: int = 5,
    module_label: str = "",
) -> tuple[Finding, ...]:
    if max_per_rule_per_file < 1:
        max_per_rule_per_file = 1
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.rule_id, []).append(finding)
    merged: list[Finding] = []
    for rule_id, items in grouped.items():
        if len(items) <= max_per_rule_per_file:
            merged.extend(items)
            continue
        merged.extend(items[:max_per_rule_per_file])
        extra = len(items) - max_per_rule_per_file
        first = items[0]
        label = module_label or first.file_path
        merged.append(
            make_finding(
                level=first.level,
                file_path=first.file_path,
                message=f"另有 {extra} 处同类问题未逐条列出",
                suggestion=f"请检查 {label} 中的同类写法并统一修改",
                rule_id=rule_id,
            )
        )
    return tuple(merged)


def empty_summary(
    *,
    entry_count: int = 0,
    skipped_file_count: int = 0,
    degraded_module_count: int = 0,
    unparsed_line_count: int = 0,
) -> CheckSummary:
    return CheckSummary(
        entry_count=entry_count,
        issue_count=0,
        must_fix_count=0,
        suggestion_count=0,
        skipped_file_count=skipped_file_count,
        degraded_module_count=degraded_module_count,
        unparsed_line_count=unparsed_line_count,
    )


def build_report(
    *,
    status: ReportStatus,
    files: Sequence[FileGroup],
    unparsed_lines: Sequence[UnparsedLine] = (),
    degraded_modules: Sequence[DegradedModule] = (),
    warnings: Sequence[str] = (),
) -> CheckReport:
    file_tuple = tuple(files)
    issue_count = 0
    must_fix_count = 0
    suggestion_count = 0
    skipped_file_count = 0
    for group in file_tuple:
        if group.skip_reason is not None:
            skipped_file_count += 1
        for finding in group.findings:
            issue_count += 1
            if finding.level is IssueLevel.MUST_FIX:
                must_fix_count += 1
            else:
                suggestion_count += 1
    summary = CheckSummary(
        entry_count=len(file_tuple),
        issue_count=issue_count,
        must_fix_count=must_fix_count,
        suggestion_count=suggestion_count,
        skipped_file_count=skipped_file_count,
        degraded_module_count=len(tuple(degraded_modules)),
        unparsed_line_count=len(tuple(unparsed_lines)),
    )
    return CheckReport(
        status=status,
        summary=summary,
        files=file_tuple,
        unparsed_lines=tuple(unparsed_lines),
        degraded_modules=tuple(degraded_modules),
        warnings=tuple(warnings),
    )


def validate_report(report: CheckReport) -> tuple[str, ...]:
    errors: list[str] = []
    summary = report.summary
    if summary.issue_count != summary.must_fix_count + summary.suggestion_count:
        errors.append("问题总数与必须修改数、优化建议数之和不一致")
    computed_must_fix = sum(
        1
        for group in report.files
        for finding in group.findings
        if finding.level is IssueLevel.MUST_FIX
    )
    computed_suggestion = sum(
        1
        for group in report.files
        for finding in group.findings
        if finding.level is IssueLevel.SUGGESTION
    )
    if summary.must_fix_count != computed_must_fix:
        errors.append("必须修改统计数与文件分组不一致")
    if summary.suggestion_count != computed_suggestion:
        errors.append("优化建议统计数与文件分组不一致")
    computed_skipped = sum(1 for group in report.files if group.skip_reason is not None)
    if summary.skipped_file_count != computed_skipped:
        errors.append("跳过文件统计数与文件分组不一致")
    if summary.degraded_module_count != len(report.degraded_modules):
        errors.append("降级模块统计数与降级列表长度不一致")
    if summary.unparsed_line_count != len(report.unparsed_lines):
        errors.append("无法解析行统计数与列表长度不一致")
    if summary.entry_count != len(report.files):
        errors.append("条目总数与文件分组数量不一致")
    return tuple(errors)
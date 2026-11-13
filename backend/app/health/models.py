from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from ..core.rules.common.models import IssueLevel


class HealthStatus(Enum):
    OK = "正常"
    PARTIAL_DEGRADED = "部分降级"
    INPUT_ERROR = "输入错误"


class RiskLevel(Enum):
    HIGH = "高风险"
    SUGGESTION = "建议"


RISK_BY_LEVEL: Mapping[IssueLevel, RiskLevel] = {
    IssueLevel.MUST_FIX: RiskLevel.HIGH,
    IssueLevel.SUGGESTION: RiskLevel.SUGGESTION,
}
SOURCE_MODULE_BY_PREFIX: Mapping[str, str] = {
    "naming": "命名与目录检查",
    "code": "代码检查",
    "link": "链接检查",
    "sens": "敏感信息与大文件检查",
}
DEGRADED_ORDER: tuple[str, ...] = (
    "遍历",
    "Git",
    "命名与目录检查",
    "代码检查",
    "链接检查",
    "敏感信息与大文件检查",
    "Demo 识别",
    "报告",
)


@dataclass(frozen=True, slots=True)
class ScanMeta:
    format_version: str = "1.0"
    scan_root: str = "<repo>"
    file_count: int = 0
    markdown_count: int = 0
    code_file_count: int = 0
    demo_project_count: int = 0
    demo_project_suspected_count: int = 0
    scanned_at: str = ""
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class HealthOptions:
    zombie_days: int = 365
    git_mode: str = "auto"
    max_files: int = 5000
    max_depth: int = 64
    enable_zombie: bool = True
    now: datetime.datetime | None = None


@dataclass(frozen=True, slots=True)
class HealthIssue:
    rule_id: str
    source_module: str
    risk_level: RiskLevel
    line_no: int | None
    message: str
    suggestion: str
    excerpt: str | None


HealthFinding = HealthIssue


@dataclass(frozen=True, slots=True)
class HealthFileEntry:
    file_path: str
    risk_level: RiskLevel
    issue_count: int
    findings: tuple[HealthIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ZombieCandidate:
    file_path: str
    basis: str
    last_activity: str
    idle_days: int
    reference_count: int
    risk_level: RiskLevel
    suggestion: str


@dataclass(frozen=True, slots=True)
class UndeterminedItem:
    item: str
    reason: str


@dataclass(frozen=True, slots=True)
class DegradedItem:
    item: str
    reason: str


@dataclass(frozen=True, slots=True)
class HealthSummary:
    issue_count: int
    must_fix_count: int
    suggestion_count: int
    zombie_candidate_count: int
    undetermined_count: int
    skipped_file_count: int
    degraded_count: int


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: HealthStatus
    meta: ScanMeta
    summary: HealthSummary
    files: tuple[HealthFileEntry, ...] = ()
    zombie_candidates: tuple[ZombieCandidate, ...] = ()
    undetermined: tuple[UndeterminedItem, ...] = ()
    degraded: tuple[DegradedItem, ...] = ()
    warnings: tuple[str, ...] = ()


def risk_for_level(level: IssueLevel) -> RiskLevel:
    return RISK_BY_LEVEL[level]


def source_module_for_rule(rule_id: str) -> str:
    prefix = rule_id.split("-", 1)[0]
    return SOURCE_MODULE_BY_PREFIX.get(prefix, "报告")


def resolve_options(options: HealthOptions | None) -> tuple[HealthOptions, tuple[str, ...]]:
    current = options or HealthOptions()
    warnings: list[str] = []
    zombie_days = current.zombie_days
    if zombie_days < 30 or zombie_days > 3650:
        warnings.append("僵尸判定阈值必须在 30～3650 天之间，已回退默认值 365 天")
        zombie_days = 365
    git_mode = current.git_mode if current.git_mode in ("auto", "on", "off") else "auto"
    if git_mode != current.git_mode:
        warnings.append("Git 依据模式非法，已回退为 auto")
    max_files = current.max_files
    if max_files < 30 or max_files > 50000:
        warnings.append("文件数上限必须在 30～50000 之间，已回退默认值 5000")
        max_files = 5000
    max_depth = current.max_depth if current.max_depth >= 1 else 64
    return (
        HealthOptions(zombie_days, git_mode, max_files, max_depth, current.enable_zombie, current.now),
        tuple(warnings),
    )


def sort_issues(issues: Sequence[HealthIssue]) -> tuple[HealthIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                0 if item.risk_level is RiskLevel.HIGH else 1,
                item.line_no is None,
                item.line_no or 0,
                item.rule_id,
                item.message,
            ),
        )
    )


def sort_files(entries: Sequence[HealthFileEntry]) -> tuple[HealthFileEntry, ...]:
    return tuple(sorted(entries, key=lambda item: item.file_path))


def sort_zombies(items: Sequence[ZombieCandidate]) -> tuple[ZombieCandidate, ...]:
    return tuple(sorted(items, key=lambda item: item.file_path))


def sort_undetermined(items: Sequence[UndeterminedItem]) -> tuple[UndeterminedItem, ...]:
    return tuple(sorted(items, key=lambda item: (item.item, item.reason)))


def sort_degraded(items: Sequence[DegradedItem]) -> tuple[DegradedItem, ...]:
    order = {name: index for index, name in enumerate(DEGRADED_ORDER)}
    unique: dict[tuple[str, str], DegradedItem] = {}
    for item in items:
        unique[(item.item, item.reason)] = item
    return tuple(sorted(unique.values(), key=lambda item: (order.get(item.item, len(order)), item.reason)))


def build_summary(
    *,
    files: Sequence[HealthFileEntry],
    zombies: Sequence[ZombieCandidate],
    undetermined: Sequence[UndeterminedItem],
    degraded: Sequence[DegradedItem],
    skipped_file_count: int,
) -> HealthSummary:
    must_fix = 0
    suggestion = 0
    for entry in files:
        for finding in entry.findings:
            if finding.risk_level is RiskLevel.HIGH:
                must_fix += 1
            else:
                suggestion += 1
    return HealthSummary(
        issue_count=must_fix + suggestion,
        must_fix_count=must_fix,
        suggestion_count=suggestion,
        zombie_candidate_count=len(zombies),
        undetermined_count=len(undetermined),
        skipped_file_count=skipped_file_count,
        degraded_count=len(degraded),
    )


def validate_health_report(report: HealthReport) -> tuple[str, ...]:
    errors: list[str] = []
    summary = report.summary
    computed_must_fix = sum(
        1
        for entry in report.files
        for finding in entry.findings
        if finding.risk_level is RiskLevel.HIGH
    )
    computed_suggestion = sum(
        1
        for entry in report.files
        for finding in entry.findings
        if finding.risk_level is RiskLevel.SUGGESTION
    )
    if summary.issue_count != summary.must_fix_count + summary.suggestion_count:
        errors.append("问题总数与分级统计不一致")
    if summary.must_fix_count != computed_must_fix:
        errors.append("高风险统计与文件明细不一致")
    if summary.suggestion_count != computed_suggestion:
        errors.append("建议统计与文件明细不一致")
    if summary.zombie_candidate_count != len(report.zombie_candidates):
        errors.append("僵尸候选统计与列表长度不一致")
    if summary.undetermined_count != len(report.undetermined):
        errors.append("无法判定统计与列表长度不一致")
    if summary.degraded_count != len(report.degraded):
        errors.append("降级统计与列表长度不一致")
    for entry in report.files:
        if entry.issue_count != len(entry.findings):
            errors.append("文件问题数与 findings 长度不一致")
            break
    return tuple(errors)
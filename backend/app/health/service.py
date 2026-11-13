from __future__ import annotations

import datetime
import time
from pathlib import Path
from typing import Sequence

from ..core.rules.common.config import RuleConfig
from ..core.rules.common.models import CheckReport, ReportStatus
from ..core.rules.engine import run_check
from ..readme.models import DemoScanResult, ReadmeOptions
from ..readme.scanner import scan_demo_projects
from ..shared.repo_walk import (
    RootValidationError,
    WalkOptions,
    WalkResult,
    resolve_default_repo,
    scan_root_name,
    to_manifest,
    validate_repo_root,
    walk_repository,
)
from ..shared.text_io import read_text_for_scan
from .models import (
    DegradedItem,
    HealthFileEntry,
    HealthIssue,
    HealthOptions,
    HealthReport,
    HealthStatus,
    HealthSummary,
    ScanMeta,
    UndeterminedItem,
    ZombieCandidate,
    build_summary,
    resolve_options,
    risk_for_level,
    sort_degraded,
    sort_files,
    sort_issues,
    sort_undetermined,
    sort_zombies,
    source_module_for_rule,
    validate_health_report,
)
from .zombie import ZombieResult, detect_zombies

MAX_DETAILED_DEGRADED: int = 50
HEALTH_FORMAT_VERSION: str = "1.0"


def resolve_repo_root(repo_root: str | Path | None = None) -> Path:
    candidate = Path(repo_root) if repo_root is not None else resolve_default_repo(Path.cwd() / "backend")
    return validate_repo_root(candidate)


def build_manifest(walk_result: WalkResult) -> str:
    return to_manifest(walk_result.files)


def map_file_entries(check_report: CheckReport, walk_result: WalkResult) -> tuple[HealthFileEntry, ...]:
    del walk_result
    entries: list[HealthFileEntry] = []
    for group in check_report.files:
        issues: list[HealthIssue] = []
        for finding in group.findings:
            issues.append(
                HealthIssue(
                    rule_id=finding.rule_id,
                    source_module=source_module_for_rule(finding.rule_id),
                    risk_level=risk_for_level(finding.level),
                    line_no=finding.line_no,
                    message=finding.message,
                    suggestion=finding.suggestion,
                    excerpt=finding.excerpt,
                )
            )
        ordered = sort_issues(issues)
        risk = "high" if any(item.risk_level.value == "高风险" for item in ordered) else "suggestion"
        entries.append(
            HealthFileEntry(
                file_path=group.file_path,
                risk_level=risk_for_level_value(risk),
                issue_count=len(ordered),
                findings=ordered,
            )
        )
    return sort_files(entries)


def risk_for_level_value(value: str):
    from .models import RiskLevel

    return RiskLevel.HIGH if value == "high" else RiskLevel.SUGGESTION


def collect_degraded(
    *,
    walk_result: WalkResult,
    check_report: CheckReport | None,
    zombie_result: ZombieResult | None,
    demo_result: DemoScanResult | None,
    extra: Sequence[tuple[str, str]] = (),
) -> tuple[DegradedItem, ...]:
    del demo_result
    items: list[DegradedItem] = []
    for skipped in walk_result.skipped:
        items.append(DegradedItem(skipped.path, skipped.reason))
    if walk_result.exceeded_max_files:
        items.append(DegradedItem("遍历", f"文件数超过上限 {walk_result.max_files}，后续文件未扫描"))
    if check_report is not None:
        for module in check_report.degraded_modules:
            items.append(DegradedItem(module.module, module.reason))
        for group in check_report.files:
            if group.skip_reason:
                items.append(DegradedItem(group.file_path, group.skip_reason))
    if zombie_result is not None:
        items.extend(zombie_result.degraded)
    for item, reason in extra:
        items.append(DegradedItem(item, reason))
    ordered = sort_degraded(items)
    if len(ordered) <= MAX_DETAILED_DEGRADED:
        return ordered
    head = ordered[:MAX_DETAILED_DEGRADED]
    return head + (DegradedItem("降级明细", f"另有 {len(ordered) - MAX_DETAILED_DEGRADED} 条降级明细未展开"),)


def make_report(
    *,
    status: HealthStatus,
    meta: ScanMeta,
    files: Sequence[HealthFileEntry],
    zombies: Sequence[ZombieCandidate],
    undetermined: Sequence[UndeterminedItem],
    degraded: Sequence[DegradedItem],
    warnings: Sequence[str],
    skipped_file_count: int,
) -> HealthReport:
    ordered_files = sort_files(files)
    ordered_zombies = sort_zombies(zombies)
    ordered_undetermined = sort_undetermined(undetermined)
    ordered_degraded = sort_degraded(degraded)
    summary = build_summary(
        files=ordered_files,
        zombies=ordered_zombies,
        undetermined=ordered_undetermined,
        degraded=ordered_degraded,
        skipped_file_count=skipped_file_count,
    )
    report = HealthReport(
        status=status,
        meta=meta,
        summary=summary,
        files=ordered_files,
        zombie_candidates=ordered_zombies,
        undetermined=ordered_undetermined,
        degraded=ordered_degraded,
        warnings=tuple(warnings),
    )
    errors = validate_health_report(report)
    if not errors:
        return report
    degraded_with_report = tuple(ordered_degraded) + (DegradedItem("报告", "统计一致性校验失败，结果可能不完整"),)
    summary = build_summary(
        files=ordered_files,
        zombies=ordered_zombies,
        undetermined=ordered_undetermined,
        degraded=degraded_with_report,
        skipped_file_count=skipped_file_count,
    )
    return HealthReport(
        status=HealthStatus.PARTIAL_DEGRADED,
        meta=meta,
        summary=summary,
        files=ordered_files,
        zombie_candidates=ordered_zombies,
        undetermined=ordered_undetermined,
        degraded=degraded_with_report,
        warnings=tuple(warnings) + ("部分统计字段可能不一致",),
    )


def input_error_report(reason: str, *, scan_root: str = "<repo>", duration_ms: int = 0) -> HealthReport:
    return HealthReport(
        status=HealthStatus.INPUT_ERROR,
        meta=ScanMeta(format_version=HEALTH_FORMAT_VERSION, scan_root=scan_root, duration_ms=duration_ms),
        summary=HealthSummary(0, 0, 0, 0, 0, 0, 0),
        warnings=(reason,),
    )


def _now_iso(options: HealthOptions) -> str:
    current = options.now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    return current.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def run_health_check(
    repo_root: str | Path | None = None,
    options: HealthOptions | None = None,
    rule_config: RuleConfig | None = None,
) -> HealthReport:
    started = time.perf_counter()
    effective, option_warnings = resolve_options(options)
    try:
        root = resolve_repo_root(repo_root)
    except RootValidationError as exc:
        return input_error_report(
            exc.reason,
            scan_root=exc.scan_root,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    walk_options = WalkOptions(max_files=effective.max_files, max_depth=effective.max_depth)
    walked = walk_repository(root, walk_options)
    demo_result = scan_demo_projects(root, walked, ReadmeOptions(max_files=effective.max_files, max_depth=effective.max_depth))
    check_report: CheckReport | None = None
    engine_degraded: list[tuple[str, str]] = []
    if walked.files:
        try:
            check_report = run_check(build_manifest(walked), root, rule_config)
        except Exception:
            check_report = None
            engine_degraded.append(("代码检查", "规则引擎执行异常，结果可能不完整"))
    zombie_result = detect_zombies(
        root,
        walked.files,
        effective,
        text_reader=lambda item: read_text_for_scan(item.absolute_path).text,
    )

    files = map_file_entries(check_report, walked) if check_report is not None else tuple()
    degraded = collect_degraded(
        walk_result=walked,
        check_report=check_report,
        zombie_result=zombie_result,
        demo_result=demo_result,
        extra=tuple(engine_degraded),
    )
    undetermined = list(zombie_result.undetermined)
    for item in demo_result.undetermined:
        undetermined.append(UndeterminedItem(item.path, item.reason))
    warnings: list[str] = list(option_warnings)
    if check_report is not None:
        warnings.extend(check_report.warnings)
    if walked.exceeded_max_files:
        warnings.append("文件数超过巡检上限，请缩小巡检范围后重试")
    if not walked.files:
        warnings.append("仓库内未发现可巡检文件")

    status = HealthStatus.OK
    if walked.exceeded_max_files or degraded:
        status = HealthStatus.PARTIAL_DEGRADED
    if check_report is not None and check_report.status is ReportStatus.PARTIAL_DEGRADED:
        status = HealthStatus.PARTIAL_DEGRADED

    skipped_file_count = walked.skipped_count
    if check_report is not None:
        skipped_file_count += sum(1 for group in check_report.files if group.skip_reason)

    meta = ScanMeta(
        format_version=HEALTH_FORMAT_VERSION,
        scan_root=scan_root_name(root),
        file_count=walked.file_count,
        markdown_count=walked.markdown_count,
        code_file_count=walked.code_file_count,
        demo_project_count=len(demo_result.confirmed),
        demo_project_suspected_count=len(demo_result.suspected),
        scanned_at=_now_iso(effective),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return make_report(
        status=status,
        meta=meta,
        files=files,
        zombies=zombie_result.candidates,
        undetermined=undetermined,
        degraded=degraded,
        warnings=warnings,
        skipped_file_count=skipped_file_count,
    )


def exit_code_for(report: HealthReport) -> int:
    if report.status is HealthStatus.INPUT_ERROR:
        return 2
    if report.status is HealthStatus.PARTIAL_DEGRADED or report.degraded:
        return 3
    if report.summary.must_fix_count > 0:
        return 1
    return 0
from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .code_scan import check as code_scan_check
from .link_check import check as link_check_check
from .naming import check as naming_check
from .sensitive import check as sensitive_check
from .common.config import RuleConfig, build_config, default_config
from .common.file_io import (
    CheckContext,
    FileSnapshot,
    ReadErrorKind,
    create_snapshot,
    resolve_repo_path,
)
from .common.manifest import (
    ManifestReadError,
    load_manifest_text,
    merge_entries,
    parse_manifest,
)
from .common.models import (
    ChangeEntry,
    ChangeStatus,
    CheckReport,
    CheckSummary,
    DegradedModule,
    ExitCode,
    FileGroup,
    IssueLevel,
    ReportStatus,
    build_report,
    validate_report,
)
from .common.report import render_text, report_to_dict, report_to_json

MODULE_LABELS = {
    "naming": "命名与目录检查",
    "code_scan": "代码检查",
    "link_check": "链接检查",
    "sensitive": "敏感信息与大文件检查",
}

MODULE_ORDER = ("naming", "code_scan", "link_check", "sensitive")


def _finding_key(finding) -> tuple:
    return (
        0 if finding.level is IssueLevel.MUST_FIX else 1,
        finding.line_no is None,
        finding.line_no or 0,
        finding.rule_id,
        finding.message,
    )


def _run_module(
    module_name: str,
    check_function,
    entry: ChangeEntry,
    ctx: CheckContext,
    findings: dict[str, list],
    skip_reasons: dict[str, str],
    degraded: list[DegradedModule],
) -> None:
    try:
        result = check_function(entry, ctx)
    except Exception:
        degraded.append(
            DegradedModule(
                module=MODULE_LABELS[module_name],
                reason="执行异常，结果可能不完整",
            )
        )
        return
    findings[entry.path].extend(result.findings)
    if result.skip_reason and entry.path not in skip_reasons:
        skip_reasons[entry.path] = result.skip_reason


def _build_groups(
    entries: tuple[ChangeEntry, ...],
    findings: dict[str, list],
    skip_reasons: dict[str, str],
) -> tuple[FileGroup, ...]:
    groups = []
    for entry in entries:
        sorted_findings = tuple(sorted(findings.get(entry.path, ()), key=_finding_key))
        groups.append(
            FileGroup(
                file_path=entry.path,
                status=entry.status,
                findings=sorted_findings,
                skip_reason=skip_reasons.get(entry.path),
                duplicate_count=entry.duplicate_count,
            )
        )
    return tuple(sorted(groups, key=lambda group: group.file_path))


def _sort_degraded(items: list[DegradedModule]) -> tuple[DegradedModule, ...]:
    order = {label: index for index, label in enumerate(MODULE_LABELS.values())}
    unique: dict[tuple[str, str], DegradedModule] = {}
    for item in items:
        unique[(item.module, item.reason)] = item
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (order.get(item.module, len(order)), item.reason),
        )
    )


def _finalize(
    status: ReportStatus,
    groups: tuple[FileGroup, ...],
    unparsed_lines,
    degraded: list[DegradedModule],
    warnings: list[str],
) -> CheckReport:
    report = build_report(
        status=status,
        files=groups,
        unparsed_lines=unparsed_lines,
        degraded_modules=_sort_degraded(degraded),
        warnings=tuple(warnings),
    )
    errors = validate_report(report)
    if errors:
        degraded_with_summary = list(report.degraded_modules) + [
            DegradedModule("汇总入口", "统计校验失败，结果可能不完整")
        ]
        report = build_report(
            status=ReportStatus.PARTIAL_DEGRADED,
            files=groups,
            unparsed_lines=unparsed_lines,
            degraded_modules=degraded_with_summary,
            warnings=tuple(warnings) + ("部分附加信息未能输出",),
        )
    return report


def run_check(
    manifest_text: str,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport:
    effective_config = config or default_config()
    root = Path(repo_root)
    if not root.exists() or not root.is_dir():
        return build_report(
            status=ReportStatus.INPUT_ERROR,
            files=(),
            warnings=("仓库根目录不存在，请检查路径参数",),
        )

    parsed = parse_manifest(manifest_text)
    entries = merge_entries(parsed.entries)
    if not entries:
        return build_report(
            status=ReportStatus.OK,
            files=(),
            unparsed_lines=parsed.unparsed_lines,
            warnings=("变更清单为空，请确认是否已生成改动列表",),
        )

    snapshot_cache: dict[str, FileSnapshot] = {}

    def get_snapshot(relative_path: str) -> FileSnapshot:
        if relative_path not in snapshot_cache:
            snapshot_cache[relative_path] = create_snapshot(root, relative_path, effective_config)
        return snapshot_cache[relative_path]

    findings: dict[str, list] = {entry.path: [] for entry in entries}
    skip_reasons: dict[str, str] = {}
    degraded: list[DegradedModule] = []

    for entry in entries:
        naming_ctx = CheckContext(
            repo_root=root,
            config=effective_config,
            module_name="naming",
            snapshot=get_snapshot,
        )
        _run_module("naming", naming_check, entry, naming_ctx, findings, skip_reasons, degraded)

        if entry.status is ChangeStatus.DELETE:
            continue
        if entry.has_illegal_path:
            skip_reasons.setdefault(entry.path, f"路径超出仓库范围，已跳过：{entry.path}")
            continue

        resolved = resolve_repo_path(root, entry.path)

        if not resolved.is_safe:
            skip_reasons.setdefault(entry.path, f"路径超出仓库范围，已跳过：{entry.path}")
            continue
        if resolved.error_kind is ReadErrorKind.NOT_FOUND:
            skip_reasons.setdefault(entry.path, "文件不存在，已跳过内容检查")
            continue
        if resolved.error_kind is ReadErrorKind.PERMISSION:
            skip_reasons.setdefault(entry.path, "无法读取文件，已跳过内容检查")
            continue
        if resolved.error_kind is ReadErrorKind.INVALID:
            skip_reasons.setdefault(entry.path, f"路径超出仓库范围，已跳过：{entry.path}")
            continue

        base_ctx = CheckContext(
            repo_root=root,
            config=effective_config,
            module_name="",
            snapshot=get_snapshot,
        )
        lowered = entry.path.lower()
        if lowered.endswith((".py", ".c", ".h")):
            _run_module("code_scan", code_scan_check, entry, base_ctx, findings, skip_reasons, degraded)
        if lowered.endswith(".md"):
            _run_module("link_check", link_check_check, entry, base_ctx, findings, skip_reasons, degraded)
        _run_module("sensitive", sensitive_check, entry, base_ctx, findings, skip_reasons, degraded)

    groups = _build_groups(entries, findings, skip_reasons)
    warnings: list[str] = []
    total_issues = sum(len(group.findings) for group in groups)
    if total_issues == 0 and entries and all(group.skip_reason for group in groups):
        warnings.append("本次未完成任何文件检查，请确认清单与仓库路径是否匹配")

    status = ReportStatus.PARTIAL_DEGRADED if degraded else ReportStatus.OK
    return _finalize(status, groups, parsed.unparsed_lines, degraded, warnings)


def run_check_file(
    manifest_path: str | Path,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport:
    try:
        manifest_text = load_manifest_text(manifest_path)
    except ManifestReadError as exc:
        return build_report(
            status=ReportStatus.INPUT_ERROR,
            files=(),
            warnings=(f"无法读取变更清单：{manifest_path}，请确认文件存在且可读",),
        )
    return run_check(manifest_text, repo_root, config=config)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.core.rules.engine",
        description="RepoGuard 规则引擎：对学习仓库变更清单执行命名、代码、链接与敏感信息检查。",
    )
    parser.add_argument("--manifest", required=True, help="变更清单文件路径；使用 - 表示从标准输入读取")
    parser.add_argument("--repo", default=".", help="仓库根目录，默认为当前目录")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式，默认为 text")
    parser.add_argument("--output", default=None, help="额外写入 JSON 报告的文件路径")
    parser.add_argument("--config", default=None, help="JSON 配置文件路径")
    parser.add_argument("--debug", action="store_true", help="输出调试信息到标准错误")
    return parser


def exit_code_for(report: CheckReport) -> ExitCode:
    if report.status is ReportStatus.INPUT_ERROR:
        return ExitCode.INPUT_ERROR
    if report.status is ReportStatus.PARTIAL_DEGRADED:
        return ExitCode.EXECUTION_ERROR
    if report.summary.must_fix_count > 0:
        return ExitCode.MUST_FIX
    return ExitCode.OK


def _attach_warnings(report: CheckReport, extra: Sequence[str]) -> CheckReport:
    if not extra:
        return report
    return replace(report, warnings=report.warnings + tuple(extra))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    del effective_argv

    try:
        config_result = build_config(config_file=args.config)
        if args.manifest == "-":
            manifest_text = sys.stdin.read()
            report = run_check(manifest_text, args.repo, config=config_result.config)
        else:
            report = run_check_file(args.manifest, args.repo, config=config_result.config)
        report = _attach_warnings(report, config_result.warnings)

        if args.format == "json":
            output_text = report_to_json(report)
        else:
            output_text = render_text(report)
        print(output_text)

        if args.output is not None:
            try:
                Path(args.output).write_text(report_to_json(report), encoding="utf-8")
            except OSError:
                report = _attach_warnings(report, [f"无法写入输出文件：{args.output}"])
                if args.format == "json":
                    print(report_to_json(report))
                else:
                    print(render_text(report))
                return int(ExitCode.EXECUTION_ERROR)

        return int(exit_code_for(report))
    except Exception:
        if args.debug:
            print("以下为调试信息，可忽略", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        print("规则引擎执行异常，未能完成检查，请稍后重试。")
        return int(ExitCode.EXECUTION_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
from __future__ import annotations

import json

from .models import (
    CheckReport,
    IssueLevel,
    ReportStatus,
)

MODULE_LABELS = {
    "naming": "命名与目录检查",
    "code_scan": "代码检查",
    "link_check": "链接检查",
    "sensitive": "敏感信息与大文件检查",
}


def render_text(report: CheckReport) -> str:
    summary = report.summary
    lines: list[str] = [
        "RepoGuard 规则检查结果",
        f"本次共检查 {summary.entry_count} 个文件变更，发现 {summary.issue_count} 个问题：",
        f"  必须修改：{summary.must_fix_count} 个    优化建议：{summary.suggestion_count} 个",
        "请先处理「必须修改」项，再根据时间采纳「优化建议」。",
    ]

    if summary.entry_count == 0:
        lines.append("")
        lines.append("变更清单为空，请确认是否已生成改动列表")

    for group in report.files:
        if not group.findings:
            continue
        level = (
            IssueLevel.MUST_FIX
            if any(item.level is IssueLevel.MUST_FIX for item in group.findings)
            else IssueLevel.SUGGESTION
        )
        lines.append("")
        lines.append(f"[{level.value}] {group.file_path}  ({group.status.value})")
        for finding in group.findings:
            if finding.line_no is not None:
                lines.append(f"  - 第 {finding.line_no} 行：{finding.message}")
            else:
                lines.append(f"  - {finding.message}")
            lines.append(f"    修改建议：{finding.suggestion}（规则标识：{finding.rule_id}）")

    if summary.issue_count == 0 and summary.entry_count > 0:
        lines.append("")
        lines.append("未发现问题")

    skipped = [group for group in report.files if group.skip_reason is not None]
    if skipped:
        lines.append("")
        lines.append("未完成检查的文件：")
        for group in skipped:
            lines.append(f"  - {group.file_path}：{group.skip_reason}")

    if report.degraded_modules:
        lines.append("")
        lines.append("模块降级说明：")
        for item in report.degraded_modules:
            lines.append(f"  - {item.module}：{item.reason}（结果可能不完整）")

    if report.warnings:
        lines.append("")
        lines.append("提示：")
        for warning in report.warnings:
            lines.append(f"  - {warning}")

    if report.degraded_modules:
        lines.append("")
        lines.append("结果可能不完整")

    if report.status is ReportStatus.INPUT_ERROR:
        lines.append("输入存在错误，本次检查未完整执行。")

    return "\n".join(lines)


def report_to_dict(report: CheckReport) -> dict[str, object]:
    summary = report.summary
    return {
        "status": report.status.value,
        "summary": {
            "entry_count": summary.entry_count,
            "issue_count": summary.issue_count,
            "must_fix_count": summary.must_fix_count,
            "suggestion_count": summary.suggestion_count,
            "skipped_file_count": summary.skipped_file_count,
            "degraded_module_count": summary.degraded_module_count,
            "unparsed_line_count": summary.unparsed_line_count,
        },
        "files": [
            {
                "file_path": group.file_path,
                "status": group.status.value,
                "duplicate_count": group.duplicate_count,
                "skip_reason": group.skip_reason,
                "findings": [
                    {
                        "level": finding.level.value,
                        "file_path": finding.file_path,
                        "message": finding.message,
                        "suggestion": finding.suggestion,
                        "rule_id": finding.rule_id,
                        "line_no": finding.line_no,
                        "excerpt": finding.excerpt,
                    }
                    for finding in group.findings
                ],
            }
            for group in report.files
        ],
        "unparsed_lines": [
            {"line_no": item.line_no, "raw": item.raw, "reason": item.reason}
            for item in report.unparsed_lines
        ],
        "degraded_modules": [
            {"module": item.module, "reason": item.reason}
            for item in report.degraded_modules
        ],
        "warnings": list(report.warnings),
    }


def _minimal_dict(report: CheckReport) -> dict[str, object]:
    return {
        "status": report.status.value,
        "summary": {
            "entry_count": report.summary.entry_count,
            "issue_count": report.summary.issue_count,
            "must_fix_count": report.summary.must_fix_count,
            "suggestion_count": report.summary.suggestion_count,
            "skipped_file_count": report.summary.skipped_file_count,
            "degraded_module_count": report.summary.degraded_module_count,
            "unparsed_line_count": report.summary.unparsed_line_count,
        },
        "files": [
            {
                "file_path": group.file_path,
                "status": group.status.value,
                "duplicate_count": group.duplicate_count,
                "skip_reason": group.skip_reason,
                "findings": [
                    {
                        "level": finding.level.value,
                        "file_path": finding.file_path,
                        "message": finding.message,
                        "suggestion": finding.suggestion,
                    }
                    for finding in group.findings
                ],
            }
            for group in report.files
        ],
        "unparsed_lines": [],
        "degraded_modules": [],
        "warnings": list(report.warnings) + ["部分附加信息未能输出"],
    }


def report_to_json(report: CheckReport) -> str:
    try:
        return json.dumps(report_to_dict(report), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return json.dumps(_minimal_dict(report), ensure_ascii=False, indent=2)
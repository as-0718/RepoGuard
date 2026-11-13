from __future__ import annotations

import json

from .models import HealthReport, HealthStatus, RiskLevel


def _issue_line(issue) -> str:
    if issue.line_no is None:
        return f"  - {issue.message}\n    修改建议：{issue.suggestion}（规则标识：{issue.rule_id}）"
    return f"  - 第 {issue.line_no} 行：{issue.message}\n    修改建议：{issue.suggestion}（规则标识：{issue.rule_id}）"


def render_health_text(report: HealthReport) -> str:
    meta = report.meta
    summary = report.summary
    if report.status is HealthStatus.INPUT_ERROR:
        return "输入存在错误，本次巡检未执行：" + (report.warnings[0] if report.warnings else "未知原因")
    lines = [
        "RepoGuard 全仓健康巡检报告",
        f"扫描根：{meta.scan_root}    文件总数：{meta.file_count}（Markdown {meta.markdown_count}、代码 {meta.code_file_count}）    Demo 工程：已确认 {meta.demo_project_count}、疑似 {meta.demo_project_suspected_count}",
        f"发现 {summary.issue_count} 个问题：高风险 {summary.must_fix_count} 个、建议 {summary.suggestion_count} 个。请先处理高风险项。",
        "",
        f"【高风险】{summary.must_fix_count} 个",
    ]
    high_files = [entry for entry in report.files if any(item.risk_level is RiskLevel.HIGH for item in entry.findings)]
    if high_files:
        for entry in high_files:
            lines.append(f"[高风险] {entry.file_path}（{entry.issue_count} 个问题）")
            for issue in entry.findings:
                if issue.risk_level is RiskLevel.HIGH:
                    lines.append(_issue_line(issue))
            lines.append("")
    else:
        lines.append("未发现高风险问题。")
        lines.append("")

    lines.append(f"【建议】{summary.suggestion_count} 个")
    suggestion_files = [entry for entry in report.files if any(item.risk_level is RiskLevel.SUGGESTION for item in entry.findings)]
    if suggestion_files:
        for entry in suggestion_files:
            lines.append(f"[建议] {entry.file_path}（{entry.issue_count} 个问题）")
            for issue in entry.findings:
                if issue.risk_level is RiskLevel.SUGGESTION:
                    lines.append(_issue_line(issue))
            lines.append("")
    else:
        lines.append("未发现建议项。")
        lines.append("")

    lines.append(f"【僵尸候选】{summary.zombie_candidate_count} 个")
    if report.zombie_candidates:
        for item in report.zombie_candidates:
            lines.append(f"  - {item.file_path}：{item.idle_days} 天未活动（依据：{item.basis}，最近活动：{item.last_activity}）")
    else:
        lines.append("未发现僵尸候选。")
    lines.append("")

    lines.append(f"【无法判定】{summary.undetermined_count} 项")
    if report.undetermined:
        for item in report.undetermined:
            lines.append(f"  - {item.item}：{item.reason}")
    else:
        lines.append("无无法判定项。")
    lines.append("")

    lines.append(f"【降级项】{summary.degraded_count} 项")
    if report.degraded:
        for item in report.degraded:
            lines.append(f"  - {item.item}：{item.reason}")
    else:
        lines.append("本次巡检未发生降级。")

    if report.warnings:
        lines.append("")
        lines.append("【警告】")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines).rstrip()


def health_to_dict(report: HealthReport) -> dict[str, object]:
    meta = report.meta
    summary = report.summary
    return {
        "format_version": meta.format_version,
        "status": report.status.value,
        "scan_root": meta.scan_root,
        "file_count": meta.file_count,
        "markdown_count": meta.markdown_count,
        "code_file_count": meta.code_file_count,
        "demo_project_count": meta.demo_project_count,
        "demo_project_suspected_count": meta.demo_project_suspected_count,
        "summary": {
            "issue_count": summary.issue_count,
            "must_fix_count": summary.must_fix_count,
            "suggestion_count": summary.suggestion_count,
            "zombie_candidate_count": summary.zombie_candidate_count,
            "undetermined_count": summary.undetermined_count,
            "skipped_file_count": summary.skipped_file_count,
            "degraded_count": summary.degraded_count,
        },
        "files": [
            {
                "file_path": entry.file_path,
                "risk_level": entry.risk_level.value,
                "issue_count": entry.issue_count,
                "findings": [
                    {
                        "rule_id": issue.rule_id,
                        "source_module": issue.source_module,
                        "risk_level": issue.risk_level.value,
                        "line_no": issue.line_no,
                        "message": issue.message,
                        "suggestion": issue.suggestion,
                        "excerpt": issue.excerpt,
                    }
                    for issue in entry.findings
                ],
            }
            for entry in report.files
        ],
        "zombie_candidates": [
            {
                "file_path": item.file_path,
                "basis": item.basis,
                "last_activity": item.last_activity,
                "idle_days": item.idle_days,
                "reference_count": item.reference_count,
                "risk_level": item.risk_level.value,
                "suggestion": item.suggestion,
            }
            for item in report.zombie_candidates
        ],
        "undetermined": [{"item": item.item, "reason": item.reason} for item in report.undetermined],
        "degraded": [{"item": item.item, "reason": item.reason} for item in report.degraded],
        "warnings": list(report.warnings),
        "scanned_at": meta.scanned_at,
        "duration_ms": meta.duration_ms,
    }


def health_to_json(report: HealthReport) -> str:
    return json.dumps(health_to_dict(report), ensure_ascii=False, indent=2)
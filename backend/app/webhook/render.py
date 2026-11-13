from __future__ import annotations

from collections.abc import Sequence

from ..core.rules.common.models import CheckReport, Finding, IssueLevel
from .models import CommentPayload, NormalizedEvent
from .security import redact_text
from .settings import WebhookConfig


class RenderError(Exception):
    pass


def render_groups(report: CheckReport) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    must_fix: list[Finding] = []
    suggestions: list[Finding] = []
    for group in report.files:
        for finding in group.findings:
            if finding.level is IssueLevel.MUST_FIX:
                must_fix.append(finding)
    for group in report.files:
        for finding in group.findings:
            if finding.level is IssueLevel.SUGGESTION:
                suggestions.append(finding)
    return tuple(must_fix), tuple(suggestions)


def _marker(config: WebhookConfig, event_id: str) -> str:
    template = (
        config.openapi_profile.comment_marker_template
        if config.openapi_profile is not None
        else "<!-- repoguard:event:{event_id} -->"
    )
    return template.replace("{event_id}", event_id)


def _finding_block(finding: Finding) -> str:
    prefix = f"第 {finding.line_no} 行：" if finding.line_no is not None else ""
    return (
        f"- {prefix}{finding.message}\n"
        f"  修改建议：{finding.suggestion}（规则标识：{finding.rule_id}）"
    )


def _fit(body: str, blocks: Sequence[str], limit: int) -> tuple[str, int]:
    included: list[str] = []
    for index, block in enumerate(blocks):
        candidate = body + "\n" + "\n".join(included + [block])
        if len(candidate) > limit:
            return body + ("\n" + "\n".join(included) if included else ""), len(blocks) - index
        included.append(block)
    return body + ("\n" + "\n".join(included) if included else ""), 0


def apply_marker(text: str, marker: str) -> str:
    return text.rstrip() + "\n\n" + marker


def redact_comment(
    text: str,
    secrets: Sequence[str] = (),
    absolute_roots: Sequence[str] = (),
) -> str:
    return redact_text(text, secrets=secrets, absolute_roots=absolute_roots)


def truncate_comment(text: str, limit: int, marker: str) -> tuple[str, int, int, bool]:
    if limit <= len(marker):
        raise RenderError("评论长度上限不足以容纳来源标记")
    if len(text) + len(marker) + 2 <= limit:
        return apply_marker(text, marker), 0, 0, False
    allowed = limit - len(marker) - 3
    cut = text[:max(0, allowed)]
    block_start = cut.rfind("\n- ")
    if block_start > 0:
        cut = cut[:block_start]
    else:
        line_end = cut.rfind("\n")
        if line_end > 0:
            cut = cut[:line_end]
    return apply_marker(cut.rstrip(), marker), 0, 0, True


def render_comment(
    report: CheckReport | None,
    event: NormalizedEvent,
    config: WebhookConfig,
    *,
    executed: bool = True,
    status_reason: str | None = None,
    illegal_paths: tuple[str, ...] = (),
    absolute_roots: tuple[str, ...] = (),
    sensitive_values: tuple[str, ...] = (),
) -> CommentPayload:
    marker = _marker(config, event.event_id)
    limit = config.max_comment_chars
    if not executed or report is None:
        if status_reason and "超时" in status_reason:
            status = "超时"
            reason_text = "检查超时：本次未完成检查"
        elif status_reason and "失败" in status_reason:
            status = "失败"
            reason_text = "检查未能完成：本次未完成检查"
        else:
            status = "未执行"
            reason_text = "本次未执行检查：变更清单不可用或检查未启动"
        body = "\n".join(
            [
                "## RepoGuard 检查结果",
                "",
                f"仓库：{event.repo_label}    PR/MR：#{event.pull_request_number}",
                f"检查状态：{status}",
                reason_text,
            ]
        )
        if illegal_paths:
            body += f"\n非法路径数量：{len(illegal_paths)}"
        text = redact_comment(body, sensitive_values, absolute_roots)
        markdown, omitted_must, omitted_tip, truncated = truncate_comment(text, limit, marker)
        return CommentPayload(
            event.event_id,
            event.repo_label,
            event.pull_request_number,
            markdown,
            len(markdown),
            len(markdown.encode("utf-8")),
            truncated,
            omitted_must,
            omitted_tip,
            marker,
            status,
            0,
            0,
            0,
            0,
            0,
        )

    summary = report.summary
    status = report.status.value
    header = "\n".join(
        [
            "## RepoGuard 检查结果",
            "",
            f"仓库：{event.repo_label}    PR/MR：#{event.pull_request_number}",
            f"检查状态：{status}",
            f"问题统计：共 {summary.issue_count} 个（必须修改 {summary.must_fix_count}，优化建议 {summary.suggestion_count}）",
            f"变更文件：{len(event.changed_files)} 个（来源：{event.changed_files_source.value}）",
        ]
    )
    if illegal_paths:
        header += f"\n非法路径：{len(illegal_paths)} 条（已跳过）"
    if report.degraded_modules:
        header += f"\n降级模块：{len(report.degraded_modules)} 个"
    if summary.skipped_file_count:
        header += f"\n未完成检查文件：{summary.skipped_file_count} 个"
    if report.unparsed_lines:
        header += f"\n无法解析行：{len(report.unparsed_lines)} 条"

    if summary.issue_count == 0 and config.notify_on_clean:
        text = header + "\n\n本次检查未发现问题"
        if report.degraded_modules:
            text += "\n\n【降级说明】\n" + "\n".join(
                f"- {item.module}：{item.reason}" for item in report.degraded_modules
            )
        markdown, omitted_must, omitted_tip, truncated = truncate_comment(text, limit, marker)
        return CommentPayload(
            event.event_id,
            event.repo_label,
            event.pull_request_number,
            markdown,
            len(markdown),
            len(markdown.encode("utf-8")),
            truncated,
            omitted_must,
            omitted_tip,
            marker,
            status,
            0,
            0,
            0,
            summary.skipped_file_count,
            summary.degraded_module_count,
        )

    must, tips = render_groups(report)
    must_blocks = [_finding_block(item) for item in must]
    tip_blocks = [_finding_block(item) for item in tips]
    budget = max(200, limit - len(marker) - 2)
    body = header + "\n\n【必须修改】"
    body, omitted_must = _fit(body, must_blocks, budget)
    if not must_blocks:
        body += "\n未发现高风险问题。"
    body += "\n\n【优化建议】"
    body, omitted_tip = _fit(body, tip_blocks, budget)
    if not tip_blocks:
        body += "\n未发现建议项。"
    if report.degraded_modules:
        body += "\n\n【降级说明】\n" + "\n".join(
            f"- {item.module}：{item.reason}" for item in report.degraded_modules
        )
    if omitted_must:
        body += f"\n- 另有 {omitted_must} 条必须修改未展示（已省略）"
    if omitted_tip:
        body += f"\n- 另有 {omitted_tip} 条优化建议未展示（已省略）"
    text = redact_comment(body, sensitive_values, absolute_roots)
    markdown, extra_must, extra_tip, truncated = truncate_comment(text, limit, marker)
    return CommentPayload(
        event.event_id,
        event.repo_label,
        event.pull_request_number,
        markdown,
        len(markdown),
        len(markdown.encode("utf-8")),
        truncated or omitted_must + omitted_tip + extra_must + extra_tip > 0,
        omitted_must + extra_must,
        omitted_tip + extra_tip,
        marker,
        status,
        summary.must_fix_count,
        summary.suggestion_count,
        summary.issue_count,
        summary.skipped_file_count,
        summary.degraded_module_count,
    )
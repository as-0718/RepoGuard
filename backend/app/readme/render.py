from __future__ import annotations

import json

from .models import ReadmeReport, ReadmeStatus


def render_readme_text(report: ReadmeReport) -> str:
    if report.status is ReadmeStatus.INPUT_ERROR:
        return "输入存在错误，本次 README 扫描未执行：" + (report.warnings[0] if report.warnings else "未知原因")
    lines = [
        "RepoGuard README 目录生成报告",
        f"扫描根：{report.scan_root}    文档数：{report.document_count}    Demo 工程：已确认 {report.demo_project_count}、疑似 {report.demo_project_suspected_count}",
        f"README：{report.readme_path if report.readme_found else '未找到'}    目录区块：{'已识别 ' + (report.toc_marker_kind or '') if report.toc_block_found else '未识别'}",
        "",
        "【文档/ Demo 统计】",
        f"文档 {report.document_count} 个，Demo 已确认 {report.demo_project_count} 个，疑似 {report.demo_project_suspected_count} 个。",
        "",
        "【目录索引】",
        report.index_markdown,
        "",
        "【与现有 README 的差异】",
    ]
    if report.diffs:
        for item in report.diffs:
            detail = item.change_type
            if item.old_title or item.new_title:
                detail += f"：{item.old_title or '（无）'} → {item.new_title or '（无）'}"
            lines.append(f"  - {detail}：{item.path}")
    else:
        lines.append("  无差异或无法对比。")
    lines.extend([
        "",
        "【可直接替换的目录片段】",
        report.replacement_block,
        "",
        f"【无法判定】{len(report.undetermined)} 项",
    ])
    if report.undetermined:
        for item in report.undetermined:
            lines.append(f"  - {item.item}：{item.reason}")
    else:
        lines.append("  无无法判定项。")
    lines.append(f"【降级项】{len(report.degraded)} 项")
    if report.degraded:
        for item in report.degraded:
            lines.append(f"  - {item.item}：{item.reason}")
    else:
        lines.append("  本次扫描未发生降级。")
    if report.warnings:
        lines.append("")
        lines.append("【警告】")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    if report.readme_found and not report.toc_block_found:
        lines.append("")
        lines.append("提示：未识别现有目录区块，请人工选择插入位置；本工具不会修改 README。")
    return "\n".join(lines).rstrip()


def readme_to_dict(report: ReadmeReport) -> dict[str, object]:
    index = report.index
    return {
        "format_version": report.format_version,
        "status": report.status.value,
        "scan_root": report.scan_root,
        "document_count": report.document_count,
        "demo_project_count": report.demo_project_count,
        "demo_project_suspected_count": report.demo_project_suspected_count,
        "readme_found": report.readme_found,
        "readme_path": report.readme_path,
        "toc_block_found": report.toc_block_found,
        "toc_marker_kind": report.toc_marker_kind,
        "index": {
            "root_readme_path": index.root_readme_path,
            "document_section": {
                "name": index.document_section.name,
                "items": [
                    {
                        "kind": item.kind,
                        "path": item.path,
                        "title": item.title,
                        "depth": item.depth,
                        "link": item.link,
                        "anchor": item.anchor,
                        "confidence": item.confidence,
                    }
                    for item in index.document_section.items
                ],
            },
            "demo_section": {
                "name": index.demo_section.name,
                "items": [
                    {
                        "kind": item.kind,
                        "path": item.path,
                        "title": item.title,
                        "depth": item.depth,
                        "link": item.link,
                        "anchor": item.anchor,
                        "confidence": item.confidence,
                    }
                    for item in index.demo_section.items
                ],
            },
        },
        "index_markdown": report.index_markdown,
        "replacement_block": report.replacement_block,
        "diffs": [
            {
                "change_type": item.change_type,
                "path": item.path,
                "old_title": item.old_title,
                "new_title": item.new_title,
                "old_position": item.old_position,
                "new_position": item.new_position,
            }
            for item in report.diffs
        ],
        "undetermined": [{"item": item.item, "reason": item.reason} for item in report.undetermined],
        "degraded": [{"item": item.item, "reason": item.reason} for item in report.degraded],
        "warnings": list(report.warnings),
        "scanned_at": report.scanned_at,
        "duration_ms": report.duration_ms,
    }


def readme_to_json(report: ReadmeReport) -> str:
    return json.dumps(readme_to_dict(report), ensure_ascii=False, indent=2)
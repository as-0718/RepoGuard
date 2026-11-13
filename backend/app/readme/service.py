from __future__ import annotations

import datetime
import time
from pathlib import Path
from typing import Sequence

from ..shared.repo_walk import (
    RootValidationError,
    WalkOptions,
    resolve_default_repo,
    scan_root_name,
    validate_repo_root,
    walk_repository,
)
from ..shared.text_io import read_text_for_scan
from .compare import (
    collect_heading_anchors,
    diff_toc,
    locate_readme,
    locate_toc_block,
    render_replacement_block,
    validate_readme_path,
)
from .index import build_index, render_index_markdown
from .models import (
    ReadmeDegraded,
    ReadmeOptions,
    ReadmeReport,
    ReadmeStatus,
    ReadmeUndetermined,
    empty_index,
    sort_diffs,
    validate_readme_report,
)
from .scanner import scan_demo_projects, scan_documents

README_FORMAT_VERSION: str = "1.0"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def input_error_report(reason: str, *, scan_root: str = "<repo>", duration_ms: int = 0) -> ReadmeReport:
    index = empty_index()
    return ReadmeReport(
        status=ReadmeStatus.INPUT_ERROR,
        format_version=README_FORMAT_VERSION,
        scan_root=scan_root,
        document_count=0,
        demo_project_count=0,
        demo_project_suspected_count=0,
        readme_found=False,
        readme_path=None,
        toc_block_found=False,
        toc_marker_kind=None,
        index=index,
        index_markdown=render_index_markdown(index),
        replacement_block=render_index_markdown(index),
        warnings=(reason,),
        scanned_at=_now_iso(),
        duration_ms=duration_ms,
    )


def exit_code_for(report: ReadmeReport) -> int:
    if report.status is ReadmeStatus.INPUT_ERROR:
        return 2
    if report.status is ReadmeStatus.PARTIAL_DEGRADED or report.degraded:
        return 3
    if report.diffs:
        return 1
    return 0


def run_readme_scan(
    repo_root: str | Path | None = None,
    options: ReadmeOptions | None = None,
) -> ReadmeReport:
    started = time.perf_counter()
    effective = options or ReadmeOptions()
    candidate = Path(repo_root) if repo_root is not None else resolve_default_repo(Path.cwd() / "backend")
    try:
        root = validate_repo_root(candidate)
    except RootValidationError as exc:
        return input_error_report(exc.reason, scan_root=exc.scan_root, duration_ms=int((time.perf_counter() - started) * 1000))

    walked = walk_repository(root, WalkOptions(max_files=effective.max_files, max_depth=effective.max_depth))
    if effective.readme_path is not None:
        _, readme_error = validate_readme_path(root, effective.readme_path)
        if readme_error is not None:
            return input_error_report(
                readme_error,
                scan_root=scan_root_name(root),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
    warnings: list[str] = []
    degraded: list[ReadmeDegraded] = []
    undetermined: list[ReadmeUndetermined] = []
    for skipped in walked.skipped:
        degraded.append(ReadmeDegraded(skipped.path, skipped.reason))

    documents = scan_documents(root, walked, effective, warnings)
    demos = scan_demo_projects(root, walked, effective, warnings)
    for item in demos.undetermined:
        undetermined.append(ReadmeUndetermined(item.path, item.reason))

    readme_file = locate_readme(root, effective.readme_path)
    readme_found = readme_file is not None
    readme_relative: str | None = None
    toc_block = None
    text = ""
    if not readme_found:
        undetermined.append(ReadmeUndetermined("README.md", "仓库根未找到 README，无法做目录差异对比"))
    else:
        readme_relative = readme_file.relative_to(root).as_posix()
        read_result = read_text_for_scan(readme_file)
        if read_result.text is None:
            degraded.append(ReadmeDegraded(readme_relative, "README 内容无法解码，无法对比目录"))
            undetermined.append(ReadmeUndetermined(readme_relative, "README 内容无法读取，无法对比目录"))
        else:
            text = read_result.text
            toc_block = locate_toc_block(text)
            if toc_block is None:
                undetermined.append(ReadmeUndetermined(readme_relative, "未识别现有目录区块，无法对比"))

    anchors = collect_heading_anchors(text) if text else {}
    index = build_index(documents, demos, anchors)
    index_markdown = render_index_markdown(index)
    replacement = render_replacement_block(index, toc_block)
    diffs = diff_toc(toc_block, index) if toc_block is not None else tuple()

    status = ReadmeStatus.OK
    if undetermined or degraded:
        status = ReadmeStatus.PARTIAL_DEGRADED
    report = ReadmeReport(
        status=status,
        format_version=README_FORMAT_VERSION,
        scan_root=scan_root_name(root),
        document_count=len(documents),
        demo_project_count=len(demos.confirmed),
        demo_project_suspected_count=len(demos.suspected),
        readme_found=readme_found,
        readme_path=readme_relative,
        toc_block_found=toc_block is not None,
        toc_marker_kind=toc_block.marker_kind if toc_block is not None else None,
        index=index,
        index_markdown=index_markdown,
        replacement_block=replacement,
        diffs=sort_diffs(diffs),
        undetermined=tuple(sorted(undetermined, key=lambda item: (item.item, item.reason))),
        degraded=tuple(sorted(degraded, key=lambda item: (item.item, item.reason))),
        warnings=tuple(warnings),
        scanned_at=_now_iso(),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    errors = validate_readme_report(report)
    if errors:
        from dataclasses import replace

        report = replace(
            report,
            status=ReadmeStatus.PARTIAL_DEGRADED,
            degraded=report.degraded + (ReadmeDegraded("报告", "报告结构校验失败，结果可能不完整"),),
            warnings=report.warnings + ("部分统计字段可能不一致",),
        )
    return report
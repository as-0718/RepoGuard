from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath

from ..api.security import RepoPathError, resolve_repo_root
from ..api.settings import WebSettings, default_repo_root
from ..health.models import HealthReport, HealthStatus
from ..health.service import run_health_check
from ..readme.models import ReadmeReport, ReadmeStatus
from ..readme.service import run_readme_scan
from .models import (
    DashboardSnapshot,
    DashboardStructure,
    DemoProjection,
    DiffProjection,
    FileCount,
    IndexProjection,
    IssuePage,
    IssueRecord,
    ItemReason,
    ModuleCount,
    ModuleRisk,
    PathTitle,
    ReadmeProjection,
    RepoDescriptor,
    RuleCount,
    SectionProjection,
    SnapshotMeta,
    TocItemProjection,
    TypeCount,
)

_FIXED_MODULES = (
    "命名与目录检查",
    "代码检查",
    "链接检查",
    "敏感信息与大文件检查",
)
_MARKDOWN_EXTENSIONS = {"md", "markdown", "mdown", "mkd"}
_CODE_EXTENSIONS = {
    "py", "c", "h", "cc", "cpp", "hpp", "cs", "java", "kt", "kts", "go", "rs",
    "rb", "php", "js", "mjs", "cjs", "ts", "tsx", "jsx", "vue", "svelte",
    "swift", "m", "mm", "sh", "bash", "ps1", "bat", "cmd", "sql", "lua",
    "pl", "r", "scala", "dart", "zig", "nim", "ex", "exs", "erl", "hrl",
    "clj", "groovy", "gradle",
}
_RISK_ORDER = {"高风险": 0, "建议": 1}
_SORT_FIELDS = {"risk_level", "file_path", "line_no", "rule_id", "source_module", "message"}
_SOURCE_MODULES = {"all", *_FIXED_MODULES, "报告"}


class SnapshotUnavailableError(Exception):
    pass


def _safe_relative(text: str | None) -> str | None:
    if text is None:
        return None
    value = str(text)
    normalized = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", value) or normalized.startswith(("/", "//", "./../")):
        return PurePosixPath(normalized).name
    return normalized


def _classify_file_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lstrip(".").casefold()
    if suffix in _MARKDOWN_EXTENSIONS:
        return "markdown"
    if suffix in _CODE_EXTENSIONS:
        return "code"
    return "other"


def _flatten_issues(files: Sequence[object]) -> tuple[IssueRecord, ...]:
    records: list[IssueRecord] = []
    for file_entry in files:
        file_path = _safe_relative(getattr(file_entry, "file_path", "")) or ""
        for finding in getattr(file_entry, "findings", ()):
            records.append(
                IssueRecord(
                    file_path=file_path,
                    line_no=finding.line_no,
                    rule_id=finding.rule_id,
                    source_module=finding.source_module,
                    risk_level=finding.risk_level.value,
                    message=finding.message,
                    suggestion=finding.suggestion,
                    excerpt=finding.excerpt,
                )
            )
    return tuple(records)


def _merge_status(health: HealthStatus, readme: ReadmeStatus | None, readme_enabled: bool) -> str:
    if health is HealthStatus.INPUT_ERROR:
        return HealthStatus.INPUT_ERROR.value
    if not readme_enabled or readme is None:
        return HealthStatus.PARTIAL_DEGRADED.value
    if health is HealthStatus.PARTIAL_DEGRADED or readme is ReadmeStatus.PARTIAL_DEGRADED:
        return HealthStatus.PARTIAL_DEGRADED.value
    if readme is ReadmeStatus.INPUT_ERROR:
        return ReadmeStatus.INPUT_ERROR.value
    return HealthStatus.OK.value


def _dedupe_items(items: Sequence[ItemReason]) -> tuple[ItemReason, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[ItemReason] = []
    for item in items:
        key = (item.item, item.reason)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _dedupe_strings(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _project_readme(report: ReadmeReport) -> ReadmeProjection:
    return ReadmeProjection(
        status=report.status.value,
        format_version=report.format_version,
        document_count=report.document_count,
        demo_project_count=report.demo_project_count,
        demo_project_suspected_count=report.demo_project_suspected_count,
        readme_found=report.readme_found,
        readme_path=_safe_relative(report.readme_path),
        toc_block_found=report.toc_block_found,
        toc_marker_kind=report.toc_marker_kind,
        diffs=tuple(
            DiffProjection(
                change_type=item.change_type,
                path=_safe_relative(item.path) or "",
                old_title=item.old_title,
                new_title=item.new_title,
                old_position=item.old_position,
                new_position=item.new_position,
            )
            for item in report.diffs
        ),
        undetermined=tuple(
            ItemReason(_safe_relative(item.item) or item.item, item.reason)
            for item in report.undetermined
        ),
        degraded=tuple(
            ItemReason(_safe_relative(item.item) or item.item, item.reason)
            for item in report.degraded
        ),
        warnings=tuple(report.warnings),
        index_markdown=report.index_markdown,
    )


def _disabled_readme() -> ReadmeProjection:
    reason = "已禁用 README 扫描"
    return ReadmeProjection(
        status=ReadmeStatus.PARTIAL_DEGRADED.value,
        format_version="1.0",
        document_count=0,
        demo_project_count=0,
        demo_project_suspected_count=0,
        readme_found=False,
        readme_path=None,
        toc_block_found=False,
        toc_marker_kind=None,
        diffs=(),
        undetermined=(ItemReason("README 扫描", reason),),
        degraded=(ItemReason("README 扫描", reason),),
        warnings=(reason,),
        index_markdown="",
    )


def list_repos(settings: WebSettings) -> tuple[RepoDescriptor, ...]:
    default_root = default_repo_root(settings)
    result: list[RepoDescriptor] = []
    seen: set[str] = set()
    for root in settings.allowed_repo_roots:
        name = root.name or "repo"
        candidate = name
        if candidate.casefold() in seen:
            candidate = f"{name}-{hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:8]}"
        seen.add(candidate.casefold())
        is_default = bool(default_root is not None and root.resolve() == default_root.resolve())
        result.append(RepoDescriptor(candidate, candidate, is_default))
    return tuple(result)


def resolve_dashboard_repo(token: str | None, settings: WebSettings) -> Path:
    if not token or not token.strip():
        root = default_repo_root(settings)
        if root is None:
            raise RepoPathError("INVALID_REPO_PATH", 400, "仓库路径格式不合法", "未配置默认仓库")
        return resolve_repo_root(str(root), settings)
    mapping = {item.id.casefold(): item for item in list_repos(settings)}
    descriptor = mapping.get(token.strip().casefold())
    if descriptor is not None:
        for root in settings.allowed_repo_roots:
            if root.name == descriptor.id or root.name.casefold() == descriptor.id.casefold():
                return resolve_repo_root(str(root), settings)
    return resolve_repo_root(token, settings)


def snapshot_key(repo_root: Path) -> str:
    normalized = os.path.normcase(str(Path(repo_root).resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_snapshot(
    repo_root: Path,
    *,
    health_runner: Callable[..., HealthReport] = run_health_check,
    readme_runner: Callable[..., ReadmeReport] = run_readme_scan,
    readme_enabled: bool = True,
) -> DashboardSnapshot:
    health = health_runner(repo_root)
    if health.status is HealthStatus.INPUT_ERROR:
        raise SnapshotUnavailableError("健康巡检输入错误")
    readme: ReadmeReport | None = None
    if readme_enabled:
        readme = readme_runner(repo_root)
        if readme.status is ReadmeStatus.INPUT_ERROR:
            raise SnapshotUnavailableError("README 扫描输入错误")

    issues = _flatten_issues(health.files)
    computed_high = sum(1 for issue in issues if issue.risk_level == "高风险")
    computed_suggestion = sum(1 for issue in issues if issue.risk_level == "建议")
    degraded_items: list[ItemReason] = [
        ItemReason(_safe_relative(item.item) or item.item, item.reason) for item in health.degraded
    ]
    if readme is not None:
        degraded_items.extend(
            ItemReason(_safe_relative(item.item) or item.item, item.reason) for item in readme.degraded
        )
    else:
        degraded_items.append(ItemReason("README 扫描", "已禁用 README 扫描"))
    warnings: list[str] = list(health.warnings)
    if readme is not None:
        warnings.extend(readme.warnings)
    else:
        warnings.append("已禁用 README 扫描")
    status = _merge_status(health.status, readme.status if readme else None, readme_enabled)
    if computed_high != health.summary.must_fix_count or computed_suggestion != health.summary.suggestion_count:
        status = HealthStatus.PARTIAL_DEGRADED.value
        degraded_items.append(ItemReason("报告", "统计字段与明细不一致，结果可能不完整"))
        warnings.append("部分统计字段可能不一致")

    summary = {
        "issue_count": health.summary.issue_count,
        "must_fix_count": health.summary.must_fix_count,
        "suggestion_count": health.summary.suggestion_count,
        "zombie_candidate_count": health.summary.zombie_candidate_count,
        "undetermined_count": health.summary.undetermined_count,
        "skipped_file_count": health.summary.skipped_file_count,
        "degraded_count": health.summary.degraded_count,
    }
    module_counts: dict[str, int] = {name: 0 for name in _FIXED_MODULES}
    for issue in issues:
        module_counts[issue.source_module] = module_counts.get(issue.source_module, 0) + 1
    module_breakdown = tuple(ModuleCount(name, module_counts[name]) for name in _FIXED_MODULES)
    module_breakdown += tuple(
        ModuleCount(name, count)
        for name, count in sorted(module_counts.items())
        if name not in _FIXED_MODULES
    )
    type_counts = {"markdown": 0, "code": 0, "other": 0}
    for file_entry in health.files:
        type_counts[_classify_file_type(getattr(file_entry, "file_path", ""))] += 1
    file_type_breakdown = tuple(TypeCount(name, type_counts[name]) for name in ("markdown", "code", "other"))
    top_files = tuple(
        FileCount(_safe_relative(getattr(item, "file_path", "")) or "", item.issue_count)
        for item in sorted(
            (item for item in health.files if getattr(item, "issue_count", 0) > 0),
            key=lambda item: (-item.issue_count, getattr(item, "file_path", "")),
        )[:10]
    )
    scanned_at = health.meta.scanned_at or (readme.scanned_at if readme else "")
    if not scanned_at:
        warnings.append("扫描时间为空")
    duration_ms = health.meta.duration_ms + (readme.duration_ms if readme else 0)
    meta = SnapshotMeta(
        status=status,
        scanned_at=scanned_at,
        duration_ms=duration_ms,
        cached=False,
        cache_age_seconds=0,
        refresh_throttled=False,
        ttl_seconds=0,
        degraded=_dedupe_items(degraded_items),
        warnings=_dedupe_strings(warnings),
    )
    return DashboardSnapshot(
        repo=RepoDescriptor(repo_root.name, repo_root.name, False),
        snapshot=meta,
        summary=summary,
        risk_breakdown={
            "high": health.summary.must_fix_count,
            "suggestion": health.summary.suggestion_count,
        },
        module_breakdown=module_breakdown,
        file_type_breakdown=file_type_breakdown,
        top_files=top_files,
        files_count=len(health.files),
        zombie_candidates_count=health.summary.zombie_candidate_count,
        undetermined_count=health.summary.undetermined_count,
        issues=issues,
        readme=_project_readme(readme) if readme is not None else _disabled_readme(),
    )


def build_overview(snapshot: DashboardSnapshot) -> dict[str, object]:
    return {
        "repo": snapshot.repo,
        "snapshot": snapshot.snapshot,
        "summary": dict(snapshot.summary),
        "charts": {
            "risk_breakdown": dict(snapshot.risk_breakdown),
            "module_breakdown": snapshot.module_breakdown,
            "file_type_breakdown": snapshot.file_type_breakdown,
            "top_files": snapshot.top_files,
        },
        "files_count": snapshot.files_count,
        "zombie_candidates_count": snapshot.zombie_candidates_count,
        "undetermined_count": snapshot.undetermined_count,
    }


def _sort_key(issue: IssueRecord, field: str) -> tuple[object, ...]:
    risk = _RISK_ORDER.get(issue.risk_level, 9)
    line = (issue.line_no is None, issue.line_no or 0)
    if field == "file_path":
        return (issue.file_path, risk, *line, issue.rule_id)
    if field == "line_no":
        return (*line, issue.file_path, risk, issue.rule_id)
    if field == "rule_id":
        return (issue.rule_id, risk, issue.file_path, *line)
    if field == "source_module":
        return (issue.source_module, risk, issue.file_path, *line, issue.rule_id)
    if field == "message":
        return (issue.message, risk, issue.file_path, *line, issue.rule_id)
    return (risk, issue.file_path, *line, issue.rule_id)


def query_issues(
    snapshot: DashboardSnapshot,
    *,
    risk_level: str,
    source_module: str,
    keyword: str,
    page: int,
    page_size: int,
    sort_field: str,
    order: str,
) -> IssuePage:
    risk = risk_level.strip()
    module = source_module.strip()
    term = keyword.strip().casefold()
    if risk not in {"all", "high", "suggestion"}:
        raise ValueError("risk_level")
    if module not in _SOURCE_MODULES:
        raise ValueError("source_module")
    if sort_field not in _SORT_FIELDS:
        raise ValueError("sort")
    if order not in {"asc", "desc"}:
        raise ValueError("order")
    filtered = []
    for issue in snapshot.issues:
        if risk == "high" and issue.risk_level != "高风险":
            continue
        if risk == "suggestion" and issue.risk_level != "建议":
            continue
        if module != "all" and issue.source_module != module:
            continue
        if term and not any(
            term in value.casefold()
            for value in (issue.file_path, issue.rule_id, issue.message, issue.suggestion)
        ):
            continue
        filtered.append(issue)
    filtered.sort(key=lambda item: _sort_key(item, sort_field), reverse=(order == "desc"))
    total = len(filtered)
    total_pages = 0 if total == 0 else math.ceil(total / page_size)
    start = (page - 1) * page_size
    items = tuple(filtered[start:start + page_size])
    counts = {
        "total": total,
        "high": sum(1 for item in filtered if item.risk_level == "高风险"),
        "suggestion": sum(1 for item in filtered if item.risk_level == "建议"),
    }
    rule_counts: dict[str, int] = {}
    for issue in filtered:
        rule_counts[issue.rule_id] = rule_counts.get(issue.rule_id, 0) + 1
    rule_breakdown = tuple(
        RuleCount(rule_id, count)
        for rule_id, count in sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    )
    matrix = tuple(
        ModuleRisk(
            module_name,
            sum(1 for item in filtered if item.source_module == module_name and item.risk_level == "高风险"),
            sum(1 for item in filtered if item.source_module == module_name and item.risk_level == "建议"),
        )
        for module_name in _FIXED_MODULES
    )
    return IssuePage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        filters={"risk_level": risk, "source_module": module, "keyword": keyword},
        sort={"field": sort_field, "order": order},
        rule_breakdown=rule_breakdown,
        module_risk_matrix=matrix,
        counts=counts,
    )


def _parse_index_markdown(markdown: str) -> tuple[IndexProjection, DemoProjection, tuple[PathTitle, ...], int]:
    doc_items: list[TocItemProjection] = []
    demo_items: list[TocItemProjection] = []
    section = ""
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "## 文档索引":
            section = "doc"
            continue
        if stripped == "## Demo 工程":
            section = "demo"
            continue
        if not stripped.startswith("- ") or section not in {"doc", "demo"}:
            continue
        depth = max(0, (len(line) - len(line.lstrip(" "))) // 2)
        directory = re.match(r"^- \*\*(.*?)\*\*$", stripped)
        if directory and section == "doc":
            title = directory.group(1)
            doc_items.append(TocItemProjection("directory", title.rstrip("/") + "/", title, depth, None, None, None))
            continue
        link = re.match(r"^- \[(.*?)\]\((.*?)\)(.*)$", stripped)
        if not link:
            continue
        title, target, suffix = link.group(1), link.group(2), link.group(3)
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        target = target.replace("\\", "/")
        if section == "doc":
            doc_items.append(TocItemProjection("document", target, title, depth, target, None, None))
        else:
            suspected = "疑似" in suffix
            demo_items.append(
                TocItemProjection(
                    "demo",
                    target.rstrip("/") + "/",
                    title,
                    depth,
                    target,
                    None,
                    "suspected" if suspected else "confirmed",
                )
            )
    index = IndexProjection(
        document_section=SectionProjection("文档索引", tuple(doc_items)),
        demo_section=SectionProjection("Demo 工程", tuple(demo_items)),
        root_readme_path=None,
    )
    confirmed = tuple(PathTitle(item.path, item.title) for item in demo_items if item.confidence != "suspected")
    suspected_count = sum(1 for item in demo_items if item.confidence == "suspected")
    return index, DemoProjection(confirmed, suspected_count), confirmed, suspected_count


def build_structure(snapshot: DashboardSnapshot) -> dict[str, object]:
    index, demo, _, _ = _parse_index_markdown(snapshot.readme.index_markdown)
    demo = replace(demo, suspected_count=snapshot.readme.demo_project_suspected_count)
    return {
        "repo": snapshot.repo,
        "snapshot": snapshot.snapshot,
        "readme": snapshot.readme,
        "index": index,
        "demo": demo,
    }
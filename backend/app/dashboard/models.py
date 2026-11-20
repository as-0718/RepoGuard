from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class RepoDescriptor:
    id: str
    label: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class ItemReason:
    item: str
    reason: str


@dataclass(frozen=True, slots=True)
class ModuleCount:
    module: str
    count: int


@dataclass(frozen=True, slots=True)
class TypeCount:
    type: str
    count: int


@dataclass(frozen=True, slots=True)
class FileCount:
    file_path: str
    issue_count: int


@dataclass(frozen=True, slots=True)
class RuleCount:
    rule_id: str
    count: int


@dataclass(frozen=True, slots=True)
class CategoryCount:
    category: str
    count: int


@dataclass(frozen=True, slots=True)
class ModuleRisk:
    module: str
    high: int
    suggestion: int


@dataclass(frozen=True, slots=True)
class PathTitle:
    path: str
    title: str


@dataclass(frozen=True, slots=True)
class DiffProjection:
    change_type: str
    path: str
    old_title: str | None
    new_title: str | None
    old_position: int | None
    new_position: int | None


@dataclass(frozen=True, slots=True)
class TocItemProjection:
    kind: str
    path: str
    title: str
    depth: int
    link: str | None
    anchor: str | None
    confidence: str | None


@dataclass(frozen=True, slots=True)
class SectionProjection:
    name: str
    items: tuple[TocItemProjection, ...]


@dataclass(frozen=True, slots=True)
class IndexProjection:
    document_section: SectionProjection
    demo_section: SectionProjection
    root_readme_path: str | None


@dataclass(frozen=True, slots=True)
class DemoProjection:
    confirmed_items: tuple[PathTitle, ...]
    suspected_count: int


@dataclass(frozen=True, slots=True)
class ReadmeProjection:
    status: str
    format_version: str
    document_count: int
    demo_project_count: int
    demo_project_suspected_count: int
    readme_found: bool
    readme_path: str | None
    toc_block_found: bool
    toc_marker_kind: str | None
    diffs: tuple[DiffProjection, ...]
    undetermined: tuple[ItemReason, ...]
    degraded: tuple[ItemReason, ...]
    warnings: tuple[str, ...]
    index_markdown: str


@dataclass(frozen=True, slots=True)
class SnapshotMeta:
    status: str
    scanned_at: str
    duration_ms: int
    cached: bool
    cache_age_seconds: int
    refresh_throttled: bool
    ttl_seconds: int
    degraded: tuple[ItemReason, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueRecord:
    file_path: str
    line_no: int | None
    rule_id: str
    source_module: str
    risk_level: str
    message: str
    suggestion: str
    excerpt: str | None


@dataclass(frozen=True, slots=True)
class IssuePage:
    items: tuple[IssueRecord, ...]
    page: int
    page_size: int
    total: int
    total_pages: int
    filters: Mapping[str, str]
    sort: Mapping[str, str]
    rule_breakdown: tuple[RuleCount, ...]
    module_risk_matrix: tuple[ModuleRisk, ...]
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    repo: RepoDescriptor
    snapshot: SnapshotMeta
    summary: Mapping[str, int]
    risk_breakdown: Mapping[str, int]
    module_breakdown: tuple[ModuleCount, ...]
    category_breakdown: tuple[CategoryCount, ...]
    file_type_breakdown: tuple[TypeCount, ...]
    top_files: tuple[FileCount, ...]
    files_count: int
    zombie_candidates_count: int
    undetermined_count: int
    issues: tuple[IssueRecord, ...]
    readme: ReadmeProjection


@dataclass(frozen=True, slots=True)
class DashboardStructure:
    repo: RepoDescriptor
    snapshot: SnapshotMeta
    readme: ReadmeProjection
    index: IndexProjection
    demo: DemoProjection


def _convert(value: object) -> object:
    if isinstance(value, Path):
        raise TypeError("禁止序列化路径对象")
    if isinstance(value, Enum):
        raise TypeError("禁止序列化枚举对象")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _convert(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _convert(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_convert(item) for item in value]
    raise TypeError(f"不支持序列化类型：{type(value).__name__}")


def to_dict(value: object) -> dict[str, object]:
    converted = _convert(value)
    if not isinstance(converted, dict):
        raise TypeError("to_dict 仅接受 dataclass 或 Mapping")
    return converted
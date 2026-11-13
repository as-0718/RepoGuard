from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


class TitleSource(Enum):
    ATX = "atx"
    FALLBACK_FILENAME = "fallback_filename"


class ReadmeStatus(Enum):
    OK = "正常"
    PARTIAL_DEGRADED = "部分降级"
    INPUT_ERROR = "输入错误"


class Confidence(Enum):
    CONFIRMED = "confirmed"
    SUSPECTED = "suspected"


@dataclass(frozen=True, slots=True)
class TitleResult:
    title: str
    source: TitleSource
    line_no: int | None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class DocEntry:
    path: str
    title: str
    title_source: TitleSource
    line_no: int | None = None


@dataclass(frozen=True, slots=True)
class DemoProject:
    path: str
    confidence: Confidence
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DemoUndetermined:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class DemoScanResult:
    confirmed: tuple[DemoProject, ...] = ()
    suspected: tuple[DemoProject, ...] = ()
    undetermined: tuple[DemoUndetermined, ...] = ()


@dataclass(frozen=True, slots=True)
class TocItem:
    kind: str
    path: str
    title: str
    depth: int
    link: str | None
    anchor: str | None
    confidence: str | None


@dataclass(frozen=True, slots=True)
class TocSection:
    name: str
    items: tuple[TocItem, ...] = ()


@dataclass(frozen=True, slots=True)
class TocIndex:
    document_section: TocSection
    demo_section: TocSection
    root_readme_path: str | None = None

    @property
    def item_count(self) -> int:
        return len(self.document_section.items) + len(self.demo_section.items)

    def all_items(self) -> tuple[TocItem, ...]:
        return self.document_section.items + self.demo_section.items


@dataclass(frozen=True, slots=True)
class TocEntryRef:
    path: str
    title: str
    depth: int
    position: int
    is_demo: bool = False


@dataclass(frozen=True, slots=True)
class TocBlock:
    start_line: int
    end_line: int
    marker_kind: str
    heading_level: int
    lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadmeDiff:
    change_type: str
    path: str
    old_title: str | None
    new_title: str | None
    old_position: int | None
    new_position: int | None


@dataclass(frozen=True, slots=True)
class ReadmeUndetermined:
    item: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReadmeDegraded:
    item: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReadmeOptions:
    max_files: int = 5000
    max_depth: int = 64
    readme_path: str | None = None
    max_title_bytes: int = 262144


@dataclass(frozen=True, slots=True)
class ReadmeReport:
    status: ReadmeStatus
    format_version: str
    scan_root: str
    document_count: int
    demo_project_count: int
    demo_project_suspected_count: int
    readme_found: bool
    readme_path: str | None
    toc_block_found: bool
    toc_marker_kind: str | None
    index: TocIndex
    index_markdown: str
    replacement_block: str
    diffs: tuple[ReadmeDiff, ...] = ()
    undetermined: tuple[ReadmeUndetermined, ...] = ()
    degraded: tuple[ReadmeDegraded, ...] = ()
    warnings: tuple[str, ...] = ()
    scanned_at: str = ""
    duration_ms: int = 0


def empty_index() -> TocIndex:
    return TocIndex(
        document_section=TocSection(name="文档索引", items=()),
        demo_section=TocSection(name="Demo 工程", items=()),
    )


def sort_diffs(diffs: Sequence[ReadmeDiff]) -> tuple[ReadmeDiff, ...]:
    order = {"新增": 0, "删除": 1, "移动": 2, "标题变化": 3}
    return tuple(sorted(diffs, key=lambda item: (order.get(item.change_type, 9), item.path, item.old_title or "", item.new_title or "")))


def validate_readme_report(report: ReadmeReport) -> tuple[str, ...]:
    errors: list[str] = []
    if report.document_count < 0:
        errors.append("文档数量不能为负")
    if report.demo_project_count < 0:
        errors.append("Demo 工程数量不能为负")
    if report.demo_project_suspected_count < 0:
        errors.append("疑似 Demo 数量不能为负")
    if report.index.item_count < 0:
        errors.append("索引条目数不能为负")
    if report.readme_found and not report.readme_path:
        errors.append("README 已找到但路径为空")
    if report.toc_block_found and not report.toc_marker_kind:
        errors.append("目录区块已找到但标记类型为空")
    return tuple(errors)
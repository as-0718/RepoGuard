from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Sequence

from .models import (
    Confidence,
    DemoProject,
    DemoScanResult,
    DocEntry,
    TocIndex,
    TocItem,
    TocSection,
)

_ANCHOR_STRIP_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff\-_]+")
_SPACE_RE = re.compile(r"\s+")


def anchor_slug(title: str) -> str:
    value = title.strip().casefold()
    value = _SPACE_RE.sub("-", value)
    value = _ANCHOR_STRIP_RE.sub("", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def render_link_target(path: str, is_directory: bool = False) -> str:
    value = path.replace("\\", "/")
    if is_directory and not value.endswith("/"):
        value += "/"
    if " " in value:
        return f"<{value}>"
    return value


def _directory_items(documents: Sequence[DocEntry], anchors: Mapping[str, str]) -> list[TocItem]:
    directories: dict[str, TocItem] = {}
    for entry in documents:
        parent = Path(entry.path).parent
        if str(parent) in (".", ""):
            continue
        segments = parent.parts
        for index in range(1, len(segments) + 1):
            relative = "/".join(segments[:index])
            if relative in directories:
                continue
            anchor = anchors.get(relative) or anchors.get(Path(relative).name)
            directories[relative] = TocItem(
                kind="directory",
                path=relative + "/",
                title=relative + "/",
                depth=index - 1,
                link=None,
                anchor=anchor,
                confidence=None,
            )
    return list(directories.values())


def build_index(
    documents: Sequence[DocEntry],
    demos: DemoScanResult | Sequence[DemoProject],
    anchors: Mapping[str, str] | None = None,
) -> TocIndex:
    anchor_map = dict(anchors or {})
    if isinstance(demos, DemoScanResult):
        confirmed = list(demos.confirmed)
        suspected = list(demos.suspected)
    else:
        confirmed = [item for item in demos if item.confidence is Confidence.CONFIRMED]
        suspected = [item for item in demos if item.confidence is Confidence.SUSPECTED]

    ordered_docs = sorted(documents, key=lambda entry: entry.path)
    directory_items = _directory_items(ordered_docs, anchor_map)
    root_readme_path: str | None = None
    doc_items: list[TocItem] = []
    for entry in ordered_docs:
        depth = len(Path(entry.path).parts) - 1
        if entry.path.casefold() == "readme.md":
            root_readme_path = entry.path
            doc_items.append(
                TocItem("document", entry.path, "根 README", 0, render_link_target(entry.path), None, None)
            )
            continue
        doc_items.append(
            TocItem("document", entry.path, entry.title, depth, render_link_target(entry.path), None, None)
        )

    document_items = sorted(
        directory_items + doc_items,
        key=lambda item: (item.depth, 0 if item.kind == "directory" else 1, item.path),
    )

    demo_items: list[TocItem] = []
    for project in confirmed + suspected:
        path = project.path.rstrip("/") + "/"
        depth = max(0, len(Path(path).parts) - 1)
        demo_items.append(
            TocItem(
                kind="demo",
                path=path,
                title=Path(path.rstrip("/")).name + "/",
                depth=depth,
                link=render_link_target(path, is_directory=True),
                anchor=None,
                confidence=project.confidence.value,
            )
        )
    demo_items.sort(key=lambda item: (0 if item.confidence == "confirmed" else 1, item.path))

    return TocIndex(
        document_section=TocSection("文档索引", tuple(document_items)),
        demo_section=TocSection("Demo 工程", tuple(demo_items)),
        root_readme_path=root_readme_path,
    )


def _render_item(item: TocItem) -> str:
    indent = "  " * item.depth
    if item.kind == "directory":
        if item.anchor:
            return f"{indent}- [{item.title}](#{item.anchor})"
        return f"{indent}- **{item.title}**"
    if item.kind == "demo":
        suffix = "（疑似，待确认）" if item.confidence == "suspected" else ""
        return f"{indent}- [{item.title}]({item.link}){suffix}"
    if item.kind == "document":
        return f"{indent}- [{item.title}]({item.link})"
    return f"{indent}- {item.title}"


def render_index_markdown(index: TocIndex, with_markers: bool = False) -> str:
    lines: list[str] = []
    for section in (index.document_section, index.demo_section):
        lines.append(f"## {section.name}")
        if section.items:
            lines.extend(_render_item(item) for item in section.items)
        else:
            lines.append("（无）")
        lines.append("")
    body = "\n".join(lines).rstrip()
    if with_markers:
        return "<!-- TOC -->\n\n" + body + "\n\n<!-- /TOC -->"
    return body
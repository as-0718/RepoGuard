from __future__ import annotations

import re
from pathlib import Path

from .index import anchor_slug, render_index_markdown
from .models import (
    ReadmeDiff,
    TocBlock,
    TocEntryRef,
    TocIndex,
    TocItem,
    sort_diffs,
)

_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<target><[^>]+>|[^)]+)\)")
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_HEADING_TOC_RE = re.compile(r"^(#{1,3})[ \t]+(目录|文档目录|table of contents|contents)[ \t]*$", re.IGNORECASE)


def validate_readme_path(root: str | Path, candidate: str | Path) -> tuple[Path | None, str | None]:
    from ..shared.repo_walk import is_within_root

    try:
        root_real = Path(root).resolve()
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = root_real / path
        real = path.resolve()
    except OSError:
        return None, "README 路径无法解析"
    if not is_within_root(root_real, real):
        return None, "README 路径必须位于仓库根内"
    if not real.is_file():
        return None, "README 文件不存在"
    return real, None


def locate_readme(root: str | Path, readme_path: str | Path | None = None) -> Path | None:
    root_path = Path(root).resolve()
    candidates = []
    if readme_path is not None:
        candidates.append(Path(readme_path))
    else:
        candidates.extend([root_path / "README.md", root_path / "readme.md"])
    for candidate in candidates:
        real, error = validate_readme_path(root_path, candidate)
        if error is None and real is not None:
            return real
    return None


def locate_toc_block(text: str) -> TocBlock | None:
    lines = text.split("\n")
    lowered = [line.strip().casefold() for line in lines]
    for start, value in enumerate(lowered):
        if value == "<!-- toc -->":
            for end in range(start + 1, len(lowered)):
                if lowered[end] == "<!-- /toc -->":
                    return TocBlock(start, end, "TOC", 0, tuple(lines[start:end + 1]))
            return None
        if value == "<!-- begin toc -->":
            for end in range(start + 1, len(lowered)):
                if lowered[end] == "<!-- end toc -->":
                    return TocBlock(start, end, "BEGIN_TOC", 0, tuple(lines[start:end + 1]))
            return None
    for start, line in enumerate(lines):
        match = _HEADING_TOC_RE.match(line.strip())
        if not match:
            continue
        level = len(match.group(1))
        end = len(lines) - 1
        for probe in range(start + 1, len(lines)):
            next_match = _ATX_RE.match(lines[probe])
            if next_match and len(next_match.group(1)) <= level:
                end = probe - 1
                break
        return TocBlock(start, end, "heading", level, tuple(lines[start:end + 1]))
    return None


def parse_toc_entries(block: TocBlock) -> tuple[TocEntryRef, ...]:
    entries: list[TocEntryRef] = []
    position = 0
    for line in block.lines:
        stripped = line.lstrip(" \t")
        depth = (len(line) - len(stripped)) // 2
        for match in _LINK_RE.finditer(line):
            target = match.group("target").strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            lowered = target.casefold()
            if lowered.startswith(("http:", "https:", "mailto:", "#")):
                continue
            if target.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", target):
                continue
            path = target.split("#", 1)[0].replace("\\", "/")
            while path.startswith("./"):
                path = path[2:]
            is_demo = path.endswith("/")
            normalized = path.rstrip("/")
            if not normalized:
                continue
            position += 1
            entries.append(TocEntryRef(normalized, match.group("text").strip(), depth, position, is_demo))
    return tuple(entries)


def collect_heading_anchors(text: str) -> dict[str, str]:
    anchors: dict[str, str] = {}
    counts: dict[str, int] = {}
    in_fence = False
    fence_char = ""
    fence_length = 0
    for line in text.split("\n"):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
            continue
        match = _ATX_RE.match(line)
        if not match:
            continue
        title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2).strip())
        slug = anchor_slug(title)
        if not slug:
            continue
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors[title] = slug if count == 0 else f"{slug}-{count}"
    return anchors


def _new_entries(index: TocIndex) -> list[TocItem]:
    return [item for item in index.all_items() if item.link]


def diff_toc(block: TocBlock | None, index: TocIndex) -> tuple[ReadmeDiff, ...]:
    old_entries = list(parse_toc_entries(block)) if block is not None else []
    old_map = {entry.path: entry for entry in old_entries}
    new_items = _new_entries(index)
    new_map = {item.path.rstrip("/"): item for item in new_items}
    changes: list[ReadmeDiff] = []
    for position, item in enumerate(new_items, start=1):
        key = item.path.rstrip("/")
        old = old_map.get(key)
        if old is None:
            changes.append(ReadmeDiff("新增", item.path, None, item.title, None, position))
            continue
        if old.depth != item.depth:
            changes.append(ReadmeDiff("移动", item.path, old.title, item.title, old.position, position))
        if old.title != item.title:
            changes.append(ReadmeDiff("标题变化", item.path, old.title, item.title, old.position, position))
    for old in old_entries:
        if old.path not in new_map:
            changes.append(ReadmeDiff("删除", old.path, old.title, None, old.position, None))
    return sort_diffs(changes)


def render_replacement_block(index: TocIndex, block: TocBlock | None = None) -> str:
    body = render_index_markdown(index)
    if block is None:
        return body
    if block.marker_kind == "TOC":
        return "<!-- TOC -->\n\n" + body + "\n\n<!-- /TOC -->"
    if block.marker_kind == "BEGIN_TOC":
        return "<!-- BEGIN TOC -->\n\n" + body + "\n\n<!-- END TOC -->"
    if block.marker_kind == "heading" and block.lines:
        return block.lines[0].rstrip() + "\n\n" + body
    return body
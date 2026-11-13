from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Sequence

from ..shared.repo_walk import WalkResult, walk_repository
from ..shared.text_io import normalize_newlines, read_title_source
from .models import (
    Confidence,
    DemoProject,
    DemoScanResult,
    DemoUndetermined,
    DocEntry,
    ReadmeOptions,
    TitleResult,
    TitleSource,
)

DOC_SUFFIX: str = ".md"
MAX_TITLE_LENGTH: int = 200
SOURCE_SUFFIXES: frozenset[str] = frozenset({".py", ".c", ".h", ".cpp", ".js", ".ts", ".java", ".go"})
STRONG_ENTRY_FILES: frozenset[str] = frozenset({
    "main.py", "app.py", "manage.py", "index.html", "main.c", "main.cpp",
    "main.java", "main.go",
})
STRONG_BUILD_FILES: frozenset[str] = frozenset({
    "requirements.txt", "pyproject.toml", "setup.py", "package.json",
    "pom.xml", "build.gradle", "cmakelists.txt", "makefile", "cargo.toml", "go.mod",
})
DEMO_HINT_WORDS: tuple[str, ...] = ("demo", "example", "sample", "tutorial")
DEMO_EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv",
    "env", "dist", "build", "target", "out", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".tox", ".eggs", "tests", "test", "assets",
    "docs", "notes",
})
TEST_FILE_PATTERNS: tuple[str, ...] = ("test_*.py", "*_test.py", "*.test.js", "*.spec.js")

_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _fallback_title(file_path: str) -> str:
    name = Path(file_path).name
    stem = Path(name).stem
    return stem or name


def _clean_heading(text: str) -> str:
    value = re.sub(r"[ \t]+#+[ \t]*$", "", text.strip())
    value = re.sub(r"\s+", " ", value)
    value = value.replace("`", "")
    return value


def extract_markdown_title(text: str, file_path: str) -> TitleResult:
    fallback = _fallback_title(file_path)
    if not text or not text.strip():
        return TitleResult(fallback, TitleSource.FALLBACK_FILENAME, None)
    source = normalize_newlines(text)
    lines = source.split("\n")
    index = 0
    first_nonempty = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_nonempty is not None and lines[first_nonempty].strip() == "---":
        closing = None
        for probe in range(first_nonempty + 1, len(lines)):
            marker = lines[probe].strip()
            if marker in ("---", "..."):
                closing = probe
                break
        if closing is not None:
            index = closing + 1

    in_comment = False
    fence_char = ""
    fence_length = 0
    first_h1: tuple[str, int] | None = None
    for line_no in range(index, len(lines)):
        line = lines[line_no]
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1]
            else:
                continue
        if "<!--" in line:
            before, after = line.split("<!--", 1)
            if "-->" in after:
                line = before + after.split("-->", 1)[1]
            else:
                in_comment = True
                line = before
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = ""
                fence_length = 0
            continue
        if fence_char:
            continue
        match = _ATX_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        title = _clean_heading(match.group(2) or "")
        if not title:
            continue
        if level == 1:
            first_h1 = (title, line_no + 1)
            break
    if first_h1 is None:
        return TitleResult(fallback, TitleSource.FALLBACK_FILENAME, None)
    title, line_no = first_h1
    truncated = len(title) > MAX_TITLE_LENGTH
    if truncated:
        title = title[:MAX_TITLE_LENGTH]
    return TitleResult(title, TitleSource.ATX, line_no, truncated)


def is_test_file(name: str) -> bool:
    lowered = name.casefold()
    return any(fnmatch.fnmatch(lowered, pattern.casefold()) for pattern in TEST_FILE_PATTERNS)


def _source_file_count(entry_names: Sequence[str]) -> int:
    return sum(
        1
        for name in entry_names
        if Path(name).suffix.casefold() in SOURCE_SUFFIXES and not is_test_file(name)
    )


def classify_demo_directory(relative_dir: str, entry_names: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    segments = [segment for segment in relative_dir.replace("\\", "/").split("/") if segment]
    if not segments:
        return "none", ()
    if any(segment.casefold() in DEMO_EXCLUDED_DIRS for segment in segments):
        return "none", ()
    source_count = _source_file_count(entry_names)
    if source_count == 0:
        return "none", ()
    lowered = {name.casefold() for name in entry_names}
    strong = sorted(lowered & (STRONG_ENTRY_FILES | STRONG_BUILD_FILES))
    if strong:
        return "confirmed", tuple(strong)
    if source_count >= 2 and "readme.md" in lowered:
        return "suspected", (f"源码文件 {source_count} 个", "README.md")
    hint_text = relative_dir.casefold() + " " + " ".join(lowered)
    if source_count >= 1 and any(word in hint_text for word in DEMO_HINT_WORDS):
        return "suspected", ("名称含 demo/example/sample/tutorial",)
    if source_count == 1:
        return "undetermined", ("只有 1 个源码文件且缺少入口文件或构建文件，无法判定是否为 Demo 工程",)
    return "none", ()


def scan_documents(
    root: str | Path,
    walk_result: WalkResult | None = None,
    options: ReadmeOptions | None = None,
    warnings: list[str] | None = None,
) -> tuple[DocEntry, ...]:
    effective = options or ReadmeOptions()
    walked = walk_result or walk_repository(root)
    warning_list = warnings if warnings is not None else []
    entries: list[DocEntry] = []
    for item in walked.files:
        if item.suffix.casefold() != DOC_SUFFIX:
            continue
        result = read_title_source(item.absolute_path, effective.max_title_bytes)
        if result.text is None:
            title = _fallback_title(item.path)
            warning_list.append(f"标题无法读取，已使用文件名：{item.path}")
            entries.append(DocEntry(item.path, title, TitleSource.FALLBACK_FILENAME, None))
            continue
        parsed = extract_markdown_title(result.text, item.path)
        if parsed.truncated:
            warning_list.append(f"标题超过 {MAX_TITLE_LENGTH} 字符，已截断：{item.path}")
        entries.append(DocEntry(item.path, parsed.title, parsed.source, parsed.line_no))
    entries.sort(key=lambda entry: entry.path)
    return tuple(entries)


def scan_demo_projects(
    root: str | Path,
    walk_result: WalkResult | None = None,
    options: ReadmeOptions | None = None,
    warnings: list[str] | None = None,
) -> DemoScanResult:
    del options
    del warnings
    walked = walk_result or walk_repository(root)
    groups: dict[str, list[str]] = {}
    for item in walked.files:
        parent = str(Path(item.path).parent).replace("\\", "/")
        if parent in (".", ""):
            continue
        groups.setdefault(parent, []).append(Path(item.path).name)
    confirmed: list[DemoProject] = []
    suspected: list[DemoProject] = []
    undetermined: list[DemoUndetermined] = []
    for directory in sorted(groups):
        status, evidence = classify_demo_directory(directory, groups[directory])
        path = directory.rstrip("/") + "/"
        if status == "confirmed":
            confirmed.append(DemoProject(path, Confidence.CONFIRMED, evidence))
        elif status == "suspected":
            suspected.append(DemoProject(path, Confidence.SUSPECTED, evidence))
        elif status == "undetermined":
            reason = evidence[0] if evidence else "依据不足，无法判定是否为 Demo 工程"
            undetermined.append(DemoUndetermined(path, reason))
    return DemoScanResult(tuple(confirmed), tuple(suspected), tuple(undetermined))
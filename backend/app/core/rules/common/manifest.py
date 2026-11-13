from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import (
    MAX_RAW_LENGTH,
    ChangeEntry,
    ChangeStatus,
    ManifestParseResult,
    UnparsedLine,
)


class ManifestReadError(Exception):
    pass


def normalize_path(raw_path: str) -> str:
    text = raw_path.strip().replace("\\", "/")
    prefix = ""
    if text.startswith("//"):
        prefix = "//"
        text = text[2:]
    elif text.startswith("/"):
        prefix = "/"
        text = text[1:]
    while text.startswith("./"):
        text = text[2:]
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    return prefix + "/".join(segments)


def has_escaping_segments(normalized_path: str) -> bool:
    return any(segment == ".." for segment in normalized_path.split("/"))


def parse_manifest_line(
    line: str,
    line_no: int,
) -> ChangeEntry | UnparsedLine | None:
    raw = line.rstrip("\r\n")
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None

    content = raw.lstrip()
    status_char = content[0]
    if status_char.upper() not in ("A", "M", "D"):
        return UnparsedLine(line_no=line_no, raw=raw[:MAX_RAW_LENGTH], reason=f"未知状态：{status_char}")

    if len(content) < 2:
        return UnparsedLine(line_no=line_no, raw=raw[:MAX_RAW_LENGTH], reason="缺少文件路径")

    if content[1] not in (" ", "\t"):
        token = content.split()[0] if content.split() else status_char
        return UnparsedLine(line_no=line_no, raw=raw[:MAX_RAW_LENGTH], reason=f"未知状态：{token}")

    rest = content[1:].strip()
    if not rest:
        return UnparsedLine(line_no=line_no, raw=raw[:MAX_RAW_LENGTH], reason="缺少文件路径")

    path = normalize_path(rest)
    if not path:
        return UnparsedLine(line_no=line_no, raw=raw[:MAX_RAW_LENGTH], reason="缺少文件路径")

    return ChangeEntry(
        status=ChangeStatus.from_value(status_char),
        path=path,
        line_no=line_no,
        raw=raw[:MAX_RAW_LENGTH],
    )


def parse_manifest(manifest_text: str) -> ManifestParseResult:
    entries: list[ChangeEntry] = []
    unparsed: list[UnparsedLine] = []
    for line_no, line in enumerate(manifest_text.splitlines(), start=1):
        result = parse_manifest_line(line, line_no)
        if result is None:
            continue
        if isinstance(result, UnparsedLine):
            unparsed.append(result)
        else:
            entries.append(result)
    unparsed.sort(key=lambda item: item.line_no)
    return ManifestParseResult(entries=tuple(entries), unparsed_lines=tuple(unparsed))


def merge_entries(entries: Sequence[ChangeEntry]) -> tuple[ChangeEntry, ...]:
    order: list[str] = []
    latest: dict[str, ChangeEntry] = {}
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.path not in latest:
            order.append(entry.path)
            latest[entry.path] = entry
            counts[entry.path] = entry.duplicate_count
            continue
        previous = latest[entry.path]
        counts[entry.path] += entry.duplicate_count
        latest[entry.path] = ChangeEntry(
            status=entry.status,
            path=entry.path,
            line_no=previous.line_no,
            raw=entry.raw,
            duplicate_count=counts[entry.path],
        )
    return tuple(latest[path] for path in order)


def load_manifest_text(manifest_path: str | Path) -> str:
    path = Path(manifest_path)
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ManifestReadError(f"无法读取变更清单：{path}，请确认文件存在且可读") from exc
    except PermissionError as exc:
        raise ManifestReadError(f"无法读取变更清单：{path}，请确认文件存在且可读") from exc
    except OSError as exc:
        raise ManifestReadError(f"无法读取变更清单：{path}，请确认文件存在且可读") from exc

    text: str | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ManifestReadError(f"变更清单编码无法识别：{path}，请另存为 UTF-8 后重试")
    return text.replace("\r\n", "\n").replace("\r", "\n")
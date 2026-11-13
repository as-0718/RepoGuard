from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..core.rules.common.file_io import (
    TextReadResult,
    is_binary_file,
    read_text_from_disk,
)

MAX_SCAN_BYTES: int = 5 * 1024 * 1024
MAX_TITLE_BYTES: int = 256 * 1024
MAX_REFERENCE_BYTES: int = 5 * 1024 * 1024


def read_text_for_scan(path: str | Path) -> TextReadResult:
    return read_text_from_disk(Path(path), max_bytes=MAX_SCAN_BYTES)


def read_text_limited(path: str | Path, max_bytes: int) -> TextReadResult:
    return read_text_from_disk(Path(path), max_bytes=max_bytes)


def read_title_source(path: str | Path, max_bytes: int = MAX_TITLE_BYTES) -> TextReadResult:
    return read_text_limited(path, max_bytes)


def is_binary_path(path: str | Path, binary_extensions: Sequence[str]) -> bool:
    return is_binary_file(Path(path), binary_extensions)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
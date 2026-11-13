from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from .config import RuleConfig
from .models import ChangeStatus

MAX_TEXT_BYTES = 5 * 1024 * 1024


class ReadErrorKind(Enum):
    NONE = "无错误"
    OUTSIDE = "路径越界"
    NOT_FOUND = "文件不存在"
    PERMISSION = "无权限"
    ENCODING = "编码错误"
    INVALID = "非法路径"


@dataclass(frozen=True, slots=True)
class ResolvedPath:
    relative_path: str
    absolute_path: Path | None
    is_safe: bool
    error_kind: ReadErrorKind


@dataclass(frozen=True, slots=True)
class TextReadResult:
    text: str | None
    error_kind: ReadErrorKind
    error_message: str | None


def _normalize(relative_path: str) -> str:
    text = relative_path.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    return "/".join(segments)


def _is_absolute_or_unc(path: str) -> bool:
    if path.startswith("/") or path.startswith("//"):
        return True
    return bool(re.match(r"^[A-Za-z]:", path))


def resolve_repo_path(
    repo_root: str | Path,
    relative_path: str,
) -> ResolvedPath:
    raw = relative_path.strip().replace("\\", "/")
    if _is_absolute_or_unc(raw):
        return ResolvedPath(raw, None, False, ReadErrorKind.INVALID)
    normalized = _normalize(relative_path)
    if not normalized:
        return ResolvedPath(normalized, None, False, ReadErrorKind.INVALID)
    if any(segment == ".." for segment in normalized.split("/")):
        return ResolvedPath(normalized, None, False, ReadErrorKind.OUTSIDE)

    root = Path(repo_root)
    try:
        if not root.exists() or not root.is_dir():
            return ResolvedPath(normalized, None, False, ReadErrorKind.OUTSIDE)
        root_real = root.resolve()
        candidate = root / normalized
        candidate_real = candidate.resolve()
        if os.name == "nt":
            root_text = str(root_real).casefold()
            candidate_text = str(candidate_real).casefold()
            try:
                common = os.path.commonpath([root_text, candidate_text])
            except ValueError:
                return ResolvedPath(normalized, None, False, ReadErrorKind.OUTSIDE)
            if common != root_text:
                return ResolvedPath(normalized, None, False, ReadErrorKind.OUTSIDE)
        else:
            if os.path.commonpath([str(root_real), str(candidate_real)]) != str(root_real):
                return ResolvedPath(normalized, None, False, ReadErrorKind.OUTSIDE)
        if not candidate.exists():
            return ResolvedPath(normalized, None, True, ReadErrorKind.NOT_FOUND)
        return ResolvedPath(normalized, candidate, True, ReadErrorKind.NONE)
    except PermissionError:
        return ResolvedPath(normalized, None, True, ReadErrorKind.PERMISSION)
    except OSError:
        return ResolvedPath(normalized, None, False, ReadErrorKind.INVALID)


def read_text_from_disk(
    absolute_path: Path,
    *,
    max_bytes: int | None = None,
) -> TextReadResult:
    try:
        with absolute_path.open("rb") as handle:
            data = handle.read() if max_bytes is None else handle.read(max_bytes)
    except FileNotFoundError:
        return TextReadResult(None, ReadErrorKind.NOT_FOUND, "文件不存在")
    except PermissionError:
        return TextReadResult(None, ReadErrorKind.PERMISSION, "没有读取权限")
    except OSError:
        return TextReadResult(None, ReadErrorKind.INVALID, "文件读取失败")

    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for encoding in ("utf-8", "gb18030"):
        try:
            return TextReadResult(data.decode(encoding), ReadErrorKind.NONE, None)
        except UnicodeDecodeError:
            continue
    return TextReadResult(
        None,
        ReadErrorKind.ENCODING,
        "文件编码无法识别，建议另存为 UTF-8 后重试",
    )


def is_binary_file(
    absolute_path: Path,
    binary_extensions: Sequence[str],
    *,
    sample_size: int = 8192,
) -> bool:
    extension = absolute_path.suffix.lower()
    normalized_extensions = {item.lower() if item.startswith(".") else f".{item.lower()}" for item in binary_extensions}
    if extension in normalized_extensions:
        return True
    try:
        with absolute_path.open("rb") as handle:
            sample = handle.read(sample_size)
    except OSError:
        return False
    return b"\x00" in sample


class FileSnapshot:
    def __init__(
        self,
        repo_root: Path,
        relative_path: str,
        resolved: ResolvedPath,
        binary_extensions: Sequence[str],
    ) -> None:
        self._repo_root = repo_root
        self._path = relative_path
        self._resolved = resolved
        self._binary_extensions = tuple(binary_extensions)
        self._size: int | None = None
        self._is_binary: bool | None = None
        self._text_result: TextReadResult | None = None
        self._read_error: str | None = None

    @property
    def path(self) -> str:
        return self._path

    @property
    def size(self) -> int:
        if self._size is not None:
            return self._size
        if not self._resolved.is_safe or self._resolved.absolute_path is None:
            self._size = 0
            if self._resolved.error_kind is ReadErrorKind.NOT_FOUND:
                self._read_error = "文件不存在"
            elif self._resolved.error_kind is not ReadErrorKind.NONE:
                self._read_error = self._resolved.error_kind.value
            return self._size
        try:
            self._size = self._resolved.absolute_path.stat().st_size
        except FileNotFoundError:
            self._size = 0
            self._read_error = "文件不存在"
        except PermissionError:
            self._size = 0
            self._read_error = "没有读取权限"
        except OSError:
            self._size = 0
            self._read_error = "无法获取文件信息"
        return self._size

    @property
    def is_binary(self) -> bool:
        if self._is_binary is not None:
            return self._is_binary
        if self._resolved.absolute_path is None:
            self._is_binary = False
            return self._is_binary
        self._is_binary = is_binary_file(self._resolved.absolute_path, self._binary_extensions)
        return self._is_binary

    @property
    def read_error(self) -> str | None:
        _ = self.size
        return self._read_error

    def text(self) -> TextReadResult:
        if self._text_result is not None:
            return self._text_result
        if self._resolved.absolute_path is None:
            self._text_result = TextReadResult(None, self._resolved.error_kind, self._resolved.error_kind.value)
            return self._text_result
        if self.is_binary:
            self._text_result = TextReadResult(
                None,
                ReadErrorKind.ENCODING,
                "文件内容无法解码，已跳过内容检查",
            )
            return self._text_result
        self._text_result = read_text_from_disk(self._resolved.absolute_path, max_bytes=MAX_TEXT_BYTES)
        return self._text_result


def create_snapshot(
    repo_root: str | Path,
    relative_path: str,
    config: RuleConfig,
) -> FileSnapshot:
    root = Path(repo_root)
    resolved = resolve_repo_path(root, relative_path)
    return FileSnapshot(root, relative_path, resolved, config.binary_extensions)


@dataclass(frozen=True, slots=True)
class CheckContext:
    repo_root: Path
    config: RuleConfig
    module_name: str
    snapshot: Callable[[str], FileSnapshot]
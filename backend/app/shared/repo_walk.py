from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_MAX_FILES: int = 5000
MAX_WALK_DEPTH: int = 64
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv",
    "env", "dist", "build", "target", "out", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".tox", ".eggs",
})
SKIP_DIR_SUFFIXES: tuple[str, ...] = (".egg-info",)
CODE_SUFFIXES: frozenset[str] = frozenset({".py", ".c", ".h"})
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


class RootValidationError(Exception):
    def __init__(self, reason: str, *, scan_root: str = "<repo>") -> None:
        super().__init__(reason)
        self.reason = reason
        self.scan_root = scan_root


@dataclass(frozen=True, slots=True)
class WalkOptions:
    max_files: int = DEFAULT_MAX_FILES
    max_depth: int = MAX_WALK_DEPTH
    skip_dir_names: frozenset[str] = SKIP_DIR_NAMES
    follow_dir_symlinks: bool = False
    max_skipped_detail: int = 200


@dataclass(frozen=True, slots=True)
class WalkedFile:
    path: str
    absolute_path: Path
    size: int
    mtime: float
    suffix: str

    @property
    def is_markdown(self) -> bool:
        return self.suffix.lower() == ".md"

    @property
    def is_code(self) -> bool:
        return self.suffix.lower() in CODE_SUFFIXES


@dataclass(frozen=True, slots=True)
class WalkSkipped:
    path: str
    reason: str
    category: str


@dataclass(frozen=True, slots=True)
class WalkResult:
    root: Path
    scan_root: str
    files: tuple[WalkedFile, ...] = ()
    skipped: tuple[WalkSkipped, ...] = ()
    exceeded_max_files: bool = False
    max_files: int = DEFAULT_MAX_FILES
    directory_count: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def markdown_count(self) -> int:
        return sum(1 for item in self.files if item.is_markdown)

    @property
    def code_file_count(self) -> int:
        return sum(1 for item in self.files if item.is_code)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def resolve_default_repo(base: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if base is not None:
        base_path = Path(base)
        candidates.append(base_path / "demo-repo")
        candidates.append(base_path.parent / "demo-repo")
    candidates.append(Path.cwd() / "demo-repo")
    candidates.append(Path.cwd().parent / "demo-repo")
    candidates.append(PROJECT_ROOT / "demo-repo")
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return (PROJECT_ROOT / "demo-repo").resolve()


def scan_root_name(root: str | Path) -> str:
    name = Path(root).name
    return name or "<repo>"


def is_tool_source_root(root: str | Path) -> bool:
    tool_root = Path(__file__).resolve().parents[1]
    try:
        real = Path(root).resolve()
    except OSError:
        return False
    if real == tool_root:
        return True
    try:
        tool_root.relative_to(real)
        return True
    except ValueError:
        return False


def validate_repo_root(repo_root: str | Path, options: WalkOptions | None = None) -> Path:
    del options
    try:
        root = Path(repo_root).expanduser().resolve()
    except OSError as exc:
        raise RootValidationError("仓库根目录不存在或无法访问") from exc
    if not root.exists():
        raise RootValidationError("仓库根目录不存在", scan_root=scan_root_name(repo_root))
    if not root.is_dir():
        raise RootValidationError("仓库根路径不是目录", scan_root=scan_root_name(repo_root))
    if is_tool_source_root(root):
        raise RootValidationError("仓库根包含 RepoGuard 工具自身源码目录，已拒绝巡检", scan_root=scan_root_name(root))
    return root


def relative_posix(root: str | Path, path: str | Path) -> str:
    root_path = Path(root).resolve()
    target = Path(path).resolve()
    try:
        return target.relative_to(root_path).as_posix()
    except ValueError:
        return target.as_posix()


def is_within_root(root: str | Path, candidate: str | Path) -> bool:
    try:
        root_real = Path(root).resolve()
        candidate_real = Path(candidate).resolve()
        if os.name == "nt":
            root_text = str(root_real).casefold()
            candidate_text = str(candidate_real).casefold()
            return os.path.commonpath([root_text, candidate_text]) == root_text
        return os.path.commonpath([str(root_real), str(candidate_real)]) == str(root_real)
    except (OSError, ValueError):
        return False


def _lexical_relative(root: Path, path: str | Path) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _is_skipped_dir(name: str, skip_names: frozenset[str]) -> bool:
    lowered = name.casefold()
    if lowered in {item.casefold() for item in skip_names}:
        return True
    return any(lowered.endswith(suffix) for suffix in SKIP_DIR_SUFFIXES)


def walk_repository(repo_root: str | Path, options: WalkOptions | None = None) -> WalkResult:
    effective = options or WalkOptions()
    root = validate_repo_root(repo_root, effective)
    files: list[WalkedFile] = []
    skipped: list[WalkSkipped] = []
    directory_count = 0
    exceeded = False

    def add_skipped(relative: str, reason: str, category: str) -> None:
        if len(skipped) < effective.max_skipped_detail:
            skipped.append(WalkSkipped(relative, reason, category))

    def visit(directory: Path, depth: int) -> None:
        nonlocal directory_count, exceeded
        if exceeded:
            return
        directory_count += 1
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError:
            add_skipped(_lexical_relative(root, directory), "目录无法读取，已跳过", "权限")
            return
        for entry in entries:
            if exceeded:
                return
            try:
                relative = _lexical_relative(root, entry.path)
                if entry.is_symlink():
                    add_skipped(relative, "符号链接不参与巡检，已跳过", "符号链接")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if _is_skipped_dir(entry.name, effective.skip_dir_names):
                        add_skipped(relative, "技术或构建目录不参与巡检，已跳过", "跳过目录")
                        continue
                    if depth + 1 > effective.max_depth:
                        add_skipped(relative, "目录深度超过上限，已停止展开", "深度超限")
                        continue
                    visit(Path(entry.path), depth + 1)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if "\n" in entry.name or "\r" in entry.name or "\x00" in entry.name:
                    add_skipped(relative, "文件名包含控制字符，无法生成合法清单", "非法路径")
                    continue
                stat_result = entry.stat(follow_symlinks=False)
                if len(files) >= effective.max_files:
                    exceeded = True
                    return
                files.append(
                    WalkedFile(
                        path=relative,
                        absolute_path=Path(entry.path),
                        size=stat_result.st_size,
                        mtime=stat_result.st_mtime,
                        suffix=Path(entry.name).suffix,
                    )
                )
            except OSError:
                add_skipped(_lexical_relative(root, entry.path), "文件元数据无法读取，已跳过", "权限")

    visit(root, 0)
    files.sort(key=lambda item: item.path)
    skipped.sort(key=lambda item: (item.path, item.category, item.reason))
    if exceeded:
        skipped.append(WalkSkipped("<repo>", f"文件数超过上限 {effective.max_files}，后续文件未扫描", "文件上限"))
    return WalkResult(
        root=root,
        scan_root=scan_root_name(root),
        files=tuple(files),
        skipped=tuple(skipped),
        exceeded_max_files=exceeded,
        max_files=effective.max_files,
        directory_count=directory_count,
    )


def to_manifest(files: Sequence[WalkedFile]) -> str:
    lines: list[str] = []
    for item in files:
        path = item.path.replace("\\", "/")
        if not path or "\n" in path or "\r" in path or "\x00" in path:
            continue
        lines.append(f"M {path}")
    return "\n".join(lines) + ("\n" if lines else "")
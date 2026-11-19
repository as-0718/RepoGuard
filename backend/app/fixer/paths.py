from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from ..api.security import (
    _is_protected_system_dir,
    has_control_chars,
    has_parent_segment,
    is_absolute_repo_path,
    is_device_or_unc_path,
    resolve_repo_root,
)
from ..api.settings import WebSettings, default_repo_root

from .errors import (
    FIXER_BACKUP_DIR_FORBIDDEN,
    FIXER_BACKUP_PATH_FORBIDDEN,
    FIXER_INVALID_SELECTION,
    raise_fixer,
)

_SAFE_LABEL_RE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


class SymlinkTargetError(Exception):
    pass


def is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate_real = candidate.resolve()
        root_real = root.resolve()
    except OSError:
        return False
    try:
        if os.name == "nt":
            root_text = str(root_real).casefold()
            candidate_text = str(candidate_real).casefold()
            return os.path.commonpath([root_text, candidate_text]) == root_text
        return os.path.commonpath([str(root_real), str(candidate_real)]) == str(root_real)
    except ValueError:
        return False


def is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _map_identity_to_root(token: str, settings: WebSettings) -> Path | None:
    """把仓库标识（目录名 / 默认仓库名）映射到已配置的仓库根目录。

    前端在默认仓库下拉里传的是仓库标识（如 ``demo-repo``），而自选目录传的是
    绝对路径。这里先按标识匹配白名单根目录；匹配不到时返回 None，交由
    :func:`resolve_repo_root` 走原始绝对路径校验与报错口径。
    """
    candidate = token.strip().rstrip("/\\")
    if not candidate or is_absolute_repo_path(candidate):
        return None
    folded = candidate.casefold()
    for root in settings.allowed_repo_roots:
        try:
            if root.name.casefold() == folded and root.is_dir():
                return root.resolve()
        except OSError:
            continue
    default_root = default_repo_root(settings)
    if default_root is not None and default_root.name.casefold() == folded:
        return default_root
    return None


def resolve_repo(raw: str, settings: WebSettings) -> Path:
    mapped = _map_identity_to_root(raw, settings)
    if mapped is not None:
        return mapped
    return resolve_repo_root(raw, settings)


def resolve_file(repo_root: Path, relative: str) -> Path:
    if (
        not relative
        or len(relative) > 1024
        or is_absolute_repo_path(relative)
        or is_device_or_unc_path(relative)
        or has_parent_segment(relative)
        or has_control_chars(relative)
    ):
        raise_fixer(FIXER_INVALID_SELECTION, 400, "文件路径不合法")
    raw_path = repo_root / relative
    if is_symlink(raw_path):
        raise SymlinkTargetError(relative)
    candidate = raw_path.resolve(strict=False)
    if not is_within(candidate, repo_root):
        raise_fixer("REPO_FORBIDDEN", 403, "文件路径不在仓库允许范围内")
    return candidate


def resolve_backup_dir(repo_root: Path, raw: str) -> Path:
    text = raw.strip()
    if not text or len(text) > 1024 or has_control_chars(text) or is_device_or_unc_path(text):
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录不可用")
    if not is_absolute_repo_path(text):
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录必须是绝对路径")
    candidate = Path(text).expanduser().resolve(strict=False)
    if _is_protected_system_dir(candidate):
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录不能是系统敏感目录")
    if not candidate.is_dir():
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录不存在或不是目录")
    if not os.access(candidate, os.W_OK):
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录不可写")
    if is_within(candidate, repo_root):
        raise_fixer(FIXER_BACKUP_DIR_FORBIDDEN, 403, "备份目录必须位于被巡检仓库之外")
    return candidate


def resolve_backup_path(backup_root: Path, relative: str) -> Path:
    if (
        not relative
        or len(relative) > 1024
        or is_absolute_repo_path(relative)
        or is_device_or_unc_path(relative)
        or has_parent_segment(relative)
        or has_control_chars(relative)
    ):
        raise_fixer(FIXER_BACKUP_PATH_FORBIDDEN, 403, "备份路径不合法")
    candidate = (backup_root / relative).resolve(strict=False)
    if not is_within(candidate, backup_root):
        raise_fixer(FIXER_BACKUP_PATH_FORBIDDEN, 403, "备份路径越界")
    if os.path.lexists(candidate) and is_symlink(candidate):
        raise_fixer(FIXER_BACKUP_PATH_FORBIDDEN, 403, "备份路径不能是符号链接")
    return candidate


def repo_label(repo_root: Path) -> str:
    safe = _SAFE_LABEL_RE.sub("_", repo_root.name).strip("_")[:40] or "repo"
    digest = hashlib.sha256(os.path.normcase(str(repo_root.resolve())).encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"
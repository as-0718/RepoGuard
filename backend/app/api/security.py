from __future__ import annotations

import os
import re
from pathlib import Path

from app.api.settings import WebSettings, default_repo_root

MAX_REPO_LENGTH: int = 512
CONTROL_CHAR_MAX: int = 31
CONTROL_CHAR_DEL: int = 127

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class RepoPathError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.detail = detail


def has_parent_segment(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return any(segment == ".." for segment in normalized.split("/"))


def has_control_chars(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == CONTROL_CHAR_DEL for char in value)


def is_device_or_unc_path(value: str) -> bool:
    return value.startswith(("\\\\?\\", "\\\\.\\", "//", "\\\\"))


def is_absolute_repo_path(value: str) -> bool:
    return value.startswith("/") or bool(_DRIVE_RE.match(value))


# 桌面单机模式下禁止巡检的系统敏感顶层目录（不区分盘符与大小写）
_PROTECTED_TOP_DIRS = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
}


def _is_protected_system_dir(candidate: Path) -> bool:
    """判断候选目录是否为盘根或位于系统敏感顶层目录之内。"""
    try:
        real = candidate.resolve(strict=False)
    except OSError:
        return True
    if real.parent == real:  # 盘根目录，如 C:\
        return True
    parts = [part.casefold() for part in real.parts]
    # parts 形如 ('C:\\', 'Windows', 'System32', ...)，取盘符之后的第一层目录
    for part in parts[1:2]:
        if part in _PROTECTED_TOP_DIRS:
            return True
    return False


def is_within_allowed_roots(candidate: Path, settings: WebSettings) -> bool:
    if not settings.allowed_repo_roots:
        return False
    try:
        candidate_real = candidate.resolve()
    except OSError:
        return False
    for root in settings.allowed_repo_roots:
        try:
            root_real = root.resolve()
            if os.name == "nt":
                root_text = str(root_real).casefold()
                candidate_text = str(candidate_real).casefold()
                if os.path.commonpath([root_text, candidate_text]) == root_text:
                    return True
            else:
                if os.path.commonpath([str(root_real), str(candidate_real)]) == str(root_real):
                    return True
        except (OSError, ValueError):
            continue
    return False


def resolve_repo_root(raw: str, settings: WebSettings) -> Path:
    text = raw.strip()
    if not text or len(text) > MAX_REPO_LENGTH:
        raise RepoPathError("INVALID_REPO_PATH", 400, "仓库路径格式不合法")
    if has_control_chars(text) or "://" in text:
        raise RepoPathError("INVALID_REPO_PATH", 400, "仓库路径格式不合法")
    if has_parent_segment(text):
        raise RepoPathError("REPO_FORBIDDEN", 403, "不允许访问包含上级目录跳转的路径")
    if is_device_or_unc_path(text):
        raise RepoPathError("REPO_FORBIDDEN", 403, "不允许访问设备路径或网络路径")

    token = text.rstrip("/\\")

    # 桌面单机模式：允许本机任意存在的目录，仅排除系统敏感目录，不再受启动白名单限制。
    if getattr(settings, "desktop_mode", False):
        if not is_absolute_repo_path(token):
            raise RepoPathError(
                "INVALID_REPO_PATH",
                400,
                "请填写仓库的绝对路径",
                "例如 C:\\Users\\你\\Desktop\\my-project",
            )
        candidate = Path(token)
        candidate_real = candidate.resolve(strict=False)
        if _is_protected_system_dir(candidate_real):
            raise RepoPathError("REPO_FORBIDDEN", 403, "不允许访问系统敏感目录")
        if not candidate_real.exists() or not candidate_real.is_dir():
            raise RepoPathError("REPO_NOT_FOUND", 404, "仓库目录不存在或不是目录")
        return candidate_real

    if not settings.allowed_repo_roots:
        raise RepoPathError("REPO_FORBIDDEN", 403, "当前没有配置可用的仓库目录")

    candidate: Path
    default_token = (settings.default_repo or "").strip().rstrip("/\\")
    if default_token and token.casefold() == default_token.casefold():
        default_root = default_repo_root(settings)
        if default_root is None:
            raise RepoPathError("REPO_NOT_FOUND", 404, "默认仓库目录不存在或不可用")
        candidate = default_root
    elif is_absolute_repo_path(token):
        candidate = Path(token)
    else:
        default_root = default_repo_root(settings)
        if default_root is None:
            raise RepoPathError(
                "INVALID_REPO_PATH",
                400,
                "仓库路径格式不合法",
                "未配置默认仓库，请填写允许范围内的绝对路径",
            )
        candidate = default_root / token

    candidate_real = candidate.resolve(strict=False)
    if not is_within_allowed_roots(candidate_real, settings):
        raise RepoPathError("REPO_FORBIDDEN", 403, "不允许访问仓库白名单之外的路径")
    if not candidate_real.exists() or not candidate_real.is_dir():
        raise RepoPathError("REPO_NOT_FOUND", 404, "仓库目录不存在或不是目录")
    return candidate_real
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
DEFAULT_STATIC_DIR: Path = PROJECT_ROOT / "backend" / "app" / "static"
DEFAULT_DEMO_REPO: str = "demo-repo"
ALLOWED_REPOS_ENV: str = "REPOGUARD_ALLOWED_REPOS"
LEGACY_ALLOWED_REPOS_ENV: str = "REPOGUARD_ALLOWED_REPO_ROOTS"
DEFAULT_REPO_ENV: str = "REPOGUARD_DEFAULT_REPO"
MAX_MANIFEST_CHARS_ENV: str = "REPOGUARD_MAX_MANIFEST_CHARS"
MAX_MANIFEST_LINES_ENV: str = "REPOGUARD_MAX_MANIFEST_LINES"
MAX_REQUEST_BYTES_ENV: str = "REPOGUARD_MAX_REQUEST_BYTES"
REVIEW_TIMEOUT_ENV: str = "REPOGUARD_REVIEW_TIMEOUT_SECONDS"
REVIEW_CONCURRENCY_ENV: str = "REPOGUARD_REVIEW_MAX_CONCURRENCY"
QUEUE_TIMEOUT_ENV: str = "REPOGUARD_QUEUE_TIMEOUT_SECONDS"
CORS_ORIGINS_ENV: str = "REPOGUARD_CORS_ORIGINS"
STATIC_DIR_ENV: str = "REPOGUARD_STATIC_DIR"

LOGGER = logging.getLogger("repoguard.api.settings")


@dataclass(frozen=True, slots=True)
class WebSettings:
    allowed_repo_roots: tuple[Path, ...] = ()
    default_repo: str | None = DEFAULT_DEMO_REPO
    max_manifest_chars: int = 1_000_000
    max_manifest_lines: int = 5_000
    max_request_bytes: int = 2_097_152
    review_timeout_seconds: float = 30.0
    review_max_concurrency: int = 2
    queue_timeout_seconds: float = 5.0
    cors_origins: tuple[str, ...] = ()
    static_dir: Path = DEFAULT_STATIC_DIR


def default_settings() -> WebSettings:
    return WebSettings(
        allowed_repo_roots=(PROJECT_ROOT / DEFAULT_DEMO_REPO,),
        default_repo=DEFAULT_DEMO_REPO,
        static_dir=DEFAULT_STATIC_DIR,
    )


def parse_allowed_repos(raw: str) -> tuple[Path, ...]:
    if not raw or not raw.strip():
        return ()
    parts = raw.split("|") if "|" in raw else raw.split(os.pathsep)
    roots: list[Path] = []
    seen: set[str] = set()
    for part in parts:
        text = part.strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            real = path.resolve()
        except OSError:
            continue
        key = str(real).casefold() if os.name == "nt" else str(real)
        if key in seen:
            continue
        seen.add(key)
        roots.append(real)
    return tuple(roots)


def _clamp_int(value: object, default: int, low: int, high: int, name: str) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        number = int(str(value))
    except (TypeError, ValueError):
        LOGGER.warning("配置项 %s 不是合法整数，已使用默认值", name)
        return default
    if number < low or number > high:
        LOGGER.warning("配置项 %s 超出范围 [%s, %s]，已使用默认值", name, low, high)
        return default
    return number


def _clamp_float(value: object, default: float, low: float, high: float, name: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(str(value))
    except (TypeError, ValueError):
        LOGGER.warning("配置项 %s 不是合法数字，已使用默认值", name)
        return default
    if number < low or number > high:
        LOGGER.warning("配置项 %s 超出范围 [%s, %s]，已使用默认值", name, low, high)
        return default
    return number


def _valid_origin(origin: str) -> bool:
    if not origin or origin == "*" or "://" not in origin:
        return False
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.hostname or parsed.port is None:
        return False
    return parsed.path in ("", "/") and not parsed.query and not parsed.fragment


def normalize_settings(settings: WebSettings) -> WebSettings:
    roots: list[Path] = []
    seen: set[str] = set()
    for root in settings.allowed_repo_roots:
        try:
            real = Path(root).expanduser().resolve()
        except OSError:
            continue
        if not real.is_dir():
            continue
        key = str(real).casefold() if os.name == "nt" else str(real)
        if key in seen:
            continue
        seen.add(key)
        roots.append(real)

    origins: list[str] = []
    for origin in settings.cors_origins:
        text = origin.strip()
        if _valid_origin(text):
            origins.append(text.rstrip("/"))

    defaults = WebSettings()
    return replace(
        settings,
        allowed_repo_roots=tuple(roots),
        max_manifest_chars=_clamp_int(
            settings.max_manifest_chars, defaults.max_manifest_chars, 1, 2_000_000, "max_manifest_chars"
        ),
        max_manifest_lines=_clamp_int(
            settings.max_manifest_lines, defaults.max_manifest_lines, 1, 20_000, "max_manifest_lines"
        ),
        max_request_bytes=_clamp_int(
            settings.max_request_bytes, defaults.max_request_bytes, 65_536, 16_777_216, "max_request_bytes"
        ),
        review_timeout_seconds=_clamp_float(
            settings.review_timeout_seconds, defaults.review_timeout_seconds, 1.0, 120.0, "review_timeout_seconds"
        ),
        review_max_concurrency=_clamp_int(
            settings.review_max_concurrency, defaults.review_max_concurrency, 1, 8, "review_max_concurrency"
        ),
        queue_timeout_seconds=_clamp_float(
            settings.queue_timeout_seconds, defaults.queue_timeout_seconds, 0.0, 30.0, "queue_timeout_seconds"
        ),
        cors_origins=tuple(origins),
        static_dir=Path(settings.static_dir),
    )


def load_settings_from_env(env: Mapping[str, str] | None = None) -> WebSettings:
    source = os.environ if env is None else env
    defaults = WebSettings()

    main_roots = source.get(ALLOWED_REPOS_ENV)
    legacy_roots = source.get(LEGACY_ALLOWED_REPOS_ENV)
    if main_roots is not None and legacy_roots is not None:
        LOGGER.warning("主仓库白名单变量与兼容变量同时存在，已忽略兼容变量")
    roots_raw = main_roots if main_roots is not None else legacy_roots
    roots = parse_allowed_repos(roots_raw) if roots_raw else default_settings().allowed_repo_roots

    default_repo_raw = source.get(DEFAULT_REPO_ENV)
    default_repo = DEFAULT_DEMO_REPO if default_repo_raw is None else default_repo_raw.strip() or None

    cors_raw = source.get(CORS_ORIGINS_ENV, "")
    cors_parts = cors_raw.split("|") if "|" in cors_raw else cors_raw.split(",")
    cors_origins = tuple(item.strip() for item in cors_parts if item.strip())

    static_raw = source.get(STATIC_DIR_ENV)
    if static_raw:
        static_dir = Path(static_raw).expanduser()
        if not static_dir.is_absolute():
            static_dir = PROJECT_ROOT / static_dir
    else:
        static_dir = DEFAULT_STATIC_DIR

    settings = WebSettings(
        allowed_repo_roots=roots,
        default_repo=default_repo,
        max_manifest_chars=_clamp_int(
            source.get(MAX_MANIFEST_CHARS_ENV, defaults.max_manifest_chars),
            defaults.max_manifest_chars, 1, 2_000_000, "max_manifest_chars",
        ),
        max_manifest_lines=_clamp_int(
            source.get(MAX_MANIFEST_LINES_ENV, defaults.max_manifest_lines),
            defaults.max_manifest_lines, 1, 20_000, "max_manifest_lines",
        ),
        max_request_bytes=_clamp_int(
            source.get(MAX_REQUEST_BYTES_ENV, defaults.max_request_bytes),
            defaults.max_request_bytes, 65_536, 16_777_216, "max_request_bytes",
        ),
        review_timeout_seconds=_clamp_float(
            source.get(REVIEW_TIMEOUT_ENV, defaults.review_timeout_seconds),
            defaults.review_timeout_seconds, 1.0, 120.0, "review_timeout_seconds",
        ),
        review_max_concurrency=_clamp_int(
            source.get(REVIEW_CONCURRENCY_ENV, defaults.review_max_concurrency),
            defaults.review_max_concurrency, 1, 8, "review_max_concurrency",
        ),
        queue_timeout_seconds=_clamp_float(
            source.get(QUEUE_TIMEOUT_ENV, defaults.queue_timeout_seconds),
            defaults.queue_timeout_seconds, 0.0, 30.0, "queue_timeout_seconds",
        ),
        cors_origins=cors_origins,
        static_dir=static_dir,
    )
    return normalize_settings(settings)


def _is_within(candidate: Path, roots: tuple[Path, ...]) -> bool:
    if not roots:
        return False
    try:
        candidate_real = candidate.resolve()
    except OSError:
        return False
    for root in roots:
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


def default_repo_root(settings: WebSettings) -> Path | None:
    if not settings.default_repo:
        return None
    token = settings.default_repo.strip().rstrip("/\\")
    if not token:
        return None
    for root in settings.allowed_repo_roots:
        if root.name.casefold() == token.casefold() and root.is_dir():
            return root
    project_candidate = PROJECT_ROOT / token
    if project_candidate.is_dir() and _is_within(project_candidate, settings.allowed_repo_roots):
        return project_candidate.resolve()
    for root in settings.allowed_repo_roots:
        candidate = root / token
        if candidate.is_dir() and _is_within(candidate, settings.allowed_repo_roots):
            return candidate.resolve()
    return None


def settings_summary(settings: WebSettings) -> dict[str, object]:
    return {
        "allowed_repo_root_count": len(settings.allowed_repo_roots),
        "default_repo": settings.default_repo,
        "static_dir_present": settings.static_dir.is_dir(),
        "cors_origin_count": len(settings.cors_origins),
    }


def repo_label(path: Path | str, settings: WebSettings | None = None) -> str:
    if settings is not None:
        try:
            resolved = Path(path).resolve()
        except OSError:
            resolved = Path(path)
        if _is_within(resolved, settings.allowed_repo_roots):
            return resolved.name
    try:
        return Path(path).name or sha256(str(path).encode("utf-8")).hexdigest()[:8]
    except (OSError, TypeError):
        return sha256(str(path).encode("utf-8")).hexdigest()[:8]
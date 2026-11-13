from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..api.security import RepoPathError, resolve_repo_root
from ..api.settings import WebSettings
from .models import WebhookError
from .settings import WebhookConfig

_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"']+")
_UNC_RE = re.compile(r"\\\\[^\s\"']+")
_POSIX_HOME_RE = re.compile(r"/(?:home|Users)/[^\s\"']+")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


class RepoMappingError(WebhookError):
    pass


def candidate_repo_tokens(identifier: str) -> tuple[str, ...]:
    value = identifier.strip()
    result: list[str] = []

    base = value.strip("/\\")
    if base:
        result.append(base)
        last = re.split(r"[\\/]", base)[-1]
        if last and last != base:
            result.append(last)
    if value and value not in result:
        result.append(value)
    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


def _map_tokens(identifier: str, config: WebhookConfig) -> tuple[str, ...]:
    tokens: list[str] = []
    lowered = identifier.casefold()
    last = re.split(r"[\\/]", identifier.strip("/\\"))[-1].casefold()
    for key, value in config.repo_map.items():
        mapped_key = key.strip().casefold()
        if mapped_key == lowered or mapped_key == last:
            tokens.append(value)
    tokens.extend(candidate_repo_tokens(identifier))
    return tuple(dict.fromkeys(tokens))


def resolve_event_repo(
    identifier: str,
    web_settings: WebSettings,
    config: WebhookConfig,
) -> Path:
    for token in _map_tokens(identifier, config):
        try:
            return resolve_repo_root(token, web_settings)
        except RepoPathError:
            continue
    raise RepoMappingError("WEBHOOK_REPO_FORBIDDEN", 403, "仓库不在服务端允许范围内")


def safe_repo_label(identifier: str) -> str:
    value = identifier.strip().strip("/\\")
    last = re.split(r"[\\/]", value)[-1]
    if last and not any(char in last for char in ("/", "\\", ":")) and not any(ord(char) < 32 for char in last):
        return last
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8]


def redact_text(
    text: str,
    secrets: Sequence[str] = (),
    absolute_roots: Sequence[str] = (),
) -> str:
    result = text
    for secret in sorted((item for item in secrets if len(item.strip()) >= 4), key=len, reverse=True):
        result = result.replace(secret, "****")
    result = _BEARER_RE.sub("Bearer ****", result)
    result = _WINDOWS_PATH_RE.sub("****", result)
    result = _UNC_RE.sub("****", result)
    result = _POSIX_HOME_RE.sub("****", result)
    for root in sorted((item for item in absolute_roots if item.strip()), key=len, reverse=True):
        result = result.replace(root, "****")
    return result


def redact_headers(headers: Mapping[str, str], keep: Sequence[str]) -> Mapping[str, str]:
    allowed = {item.casefold() for item in keep}
    return {
        key: value
        for key, value in headers.items()
        if key.casefold() in allowed and key.casefold() not in {"authorization", "cookie"}
    }
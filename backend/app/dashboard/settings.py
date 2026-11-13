from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_PREFIX: str = "REPOGUARD_DASHBOARD_"
CACHE_TTL_ENV = "REPOGUARD_DASHBOARD_CACHE_TTL_SECONDS"
CACHE_CAPACITY_ENV = "REPOGUARD_DASHBOARD_CACHE_CAPACITY"
SCAN_TIMEOUT_ENV = "REPOGUARD_DASHBOARD_SCAN_TIMEOUT_SECONDS"
MAX_CONCURRENCY_ENV = "REPOGUARD_DASHBOARD_MAX_CONCURRENCY"
QUEUE_TIMEOUT_ENV = "REPOGUARD_DASHBOARD_QUEUE_TIMEOUT_SECONDS"
REFRESH_MIN_INTERVAL_ENV = "REPOGUARD_DASHBOARD_REFRESH_MIN_INTERVAL_SECONDS"
MAX_PAGE_SIZE_ENV = "REPOGUARD_DASHBOARD_MAX_PAGE_SIZE"
MAX_KEYWORD_LENGTH_ENV = "REPOGUARD_DASHBOARD_MAX_KEYWORD_LENGTH"
ENABLE_README_ENV = "REPOGUARD_DASHBOARD_ENABLE_README"

LOGGER = logging.getLogger("repoguard.dashboard.settings")


@dataclass(frozen=True, slots=True)
class DashboardSettings:
    cache_ttl_seconds: int = 60
    cache_capacity: int = 8
    scan_timeout_seconds: int = 30
    max_concurrency: int = 2
    queue_timeout_seconds: int = 5
    refresh_min_interval_seconds: int = 10
    max_page_size: int = 100
    max_keyword_length: int = 64
    enable_readme: bool = True


def default_dashboard_settings() -> DashboardSettings:
    return DashboardSettings()


def _int_value(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        LOGGER.warning("配置项 %s 不是合法整数，已使用默认值 %s", name, default)
        return default
    if value < low or value > high:
        LOGGER.warning("配置项 %s 超出范围 %s-%s，已使用默认值 %s", name, low, high, default)
        return default
    return value


def _bool_value(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    LOGGER.warning("配置项 %s 不是合法布尔值，已使用默认值 %s", name, default)
    return default


def load_dashboard_settings_from_env(env: Mapping[str, str] | None = None) -> DashboardSettings:
    source = os.environ if env is None else env
    defaults = DashboardSettings()
    return DashboardSettings(
        cache_ttl_seconds=_int_value(source, CACHE_TTL_ENV, defaults.cache_ttl_seconds, 0, 600),
        cache_capacity=_int_value(source, CACHE_CAPACITY_ENV, defaults.cache_capacity, 1, 32),
        scan_timeout_seconds=_int_value(source, SCAN_TIMEOUT_ENV, defaults.scan_timeout_seconds, 5, 120),
        max_concurrency=_int_value(source, MAX_CONCURRENCY_ENV, defaults.max_concurrency, 1, 4),
        queue_timeout_seconds=_int_value(source, QUEUE_TIMEOUT_ENV, defaults.queue_timeout_seconds, 0, 30),
        refresh_min_interval_seconds=_int_value(source, REFRESH_MIN_INTERVAL_ENV, defaults.refresh_min_interval_seconds, 0, 60),
        max_page_size=_int_value(source, MAX_PAGE_SIZE_ENV, defaults.max_page_size, 10, 200),
        max_keyword_length=_int_value(source, MAX_KEYWORD_LENGTH_ENV, defaults.max_keyword_length, 8, 256),
        enable_readme=_bool_value(source, ENABLE_README_ENV, defaults.enable_readme),
    )


def settings_summary(settings: DashboardSettings) -> dict[str, object]:
    return {
        "cache_ttl_seconds": settings.cache_ttl_seconds,
        "cache_capacity": settings.cache_capacity,
        "scan_timeout_seconds": settings.scan_timeout_seconds,
        "max_concurrency": settings.max_concurrency,
        "queue_timeout_seconds": settings.queue_timeout_seconds,
        "refresh_min_interval_seconds": settings.refresh_min_interval_seconds,
        "max_page_size": settings.max_page_size,
        "max_keyword_length": settings.max_keyword_length,
        "enable_readme": settings.enable_readme,
    }
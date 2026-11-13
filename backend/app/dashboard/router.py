from __future__ import annotations

import asyncio
import dataclasses
import datetime
import json
import logging
import time
from collections.abc import Callable

import fastapi
import starlette.responses


from .cache import CacheBusyError, CacheTimeoutError, SnapshotCache
from .models import DashboardSnapshot, RepoDescriptor, to_dict

from .settings import DashboardSettings, load_dashboard_settings_from_env

LOGGER = logging.getLogger("repoguard.dashboard")
router = fastapi.APIRouter(tags=["dashboard"])

_RISK_VALUES = {"all", "high", "suggestion"}
_SOURCE_VALUES = {"all", "命名与目录检查", "代码检查", "链接检查", "敏感信息与大文件检查", "报告"}
_SORT_VALUES = {"risk_level", "file_path", "line_no", "rule_id", "source_module", "message"}
_ORDER_VALUES = {"asc", "desc"}


def _raise_api(code: str, status: int, message: str, detail: str | None = None) -> None:
    from ..api.routes import ApiError

    raise ApiError(code, status, message, detail)


def get_web_settings(request: fastapi.Request) -> object:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用")
    return settings


def get_dashboard_settings(request: fastapi.Request) -> DashboardSettings:
    settings = getattr(request.app.state, "dashboard_settings", None)
    if settings is None:
        settings = load_dashboard_settings_from_env()
        request.app.state.dashboard_settings = settings
    return settings


def get_cache(request: fastapi.Request) -> SnapshotCache:
    cache = getattr(request.app.state, "dashboard_cache", None)
    if cache is None:
        settings = get_dashboard_settings(request)
        cache = SnapshotCache(
            settings.cache_ttl_seconds,
            settings.cache_capacity,
            max_concurrency=settings.max_concurrency,
            queue_timeout_seconds=settings.queue_timeout_seconds,
            refresh_min_interval_seconds=settings.refresh_min_interval_seconds,
        )
        request.app.state.dashboard_cache = cache
    return cache


def get_health_runner() -> Callable[..., object]:
    try:
        from ..health.service import run_health_check

        if not callable(run_health_check):
            raise ImportError("run_health_check 不可调用")
        return run_health_check
    except ImportError:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用")


def get_readme_runner() -> Callable[..., object]:
    try:
        from ..readme.service import run_readme_scan

        if not callable(run_readme_scan):
            raise ImportError("run_readme_scan 不可调用")
        return run_readme_scan
    except ImportError:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用")


def _request_id(request: fastapi.Request) -> str:
    return getattr(request.state, "request_id", "")


def _json_response(request: fastapi.Request, body: dict[str, object], status_code: int = 200) -> starlette.responses.JSONResponse:
    return starlette.responses.JSONResponse(
        status_code=status_code,
        content=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Request-ID": _request_id(request),
        },
    )


def _validate_choice(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        _raise_api("INVALID_QUERY_PARAM", 400, "查询参数不合法", f"字段：{name}")


def _validate_refresh(refresh: int) -> None:
    if refresh not in (0, 1):
        _raise_api("INVALID_QUERY_PARAM", 400, "查询参数不合法", "字段：refresh")


def _descriptor_for(
    root: object,
    token: str | None,
    web_settings: object,
) -> RepoDescriptor:
    from .service import list_repos
    from ..api.settings import default_repo_root

    repos = list_repos(web_settings)
    default_root = default_repo_root(web_settings)
    if token:
        for item in repos:
            if item.id.casefold() == token.strip().casefold():
                return item
    for item in repos:
        if item.is_default:
            return item
    name = getattr(root, "name", "repo")
    is_default = bool(default_root is not None and getattr(root, "resolve", lambda: root)() == default_root.resolve())
    return RepoDescriptor(name, name, is_default)


async def _prepare(
    request: fastapi.Request,
    repo: str | None,
    refresh: int,
    web_settings: object,
    dashboard_settings: DashboardSettings,
    cache: SnapshotCache,
    health_runner: Callable[..., object],
    readme_runner: Callable[..., object],
) -> DashboardSnapshot:
    from .service import (
        SnapshotUnavailableError,
        load_snapshot,
        resolve_dashboard_repo,
        snapshot_key,
    )
    from ..api.routes import ApiError
    from ..api.security import RepoPathError

    _validate_refresh(refresh)
    if not web_settings.allowed_repo_roots:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用", "未配置可用的仓库目录")
    root = resolve_dashboard_repo(repo, web_settings)
    descriptor = _descriptor_for(root, repo, web_settings)
    key = snapshot_key(root)
    deadline = time.monotonic() + dashboard_settings.scan_timeout_seconds
    loader = lambda: load_snapshot(
        root,
        health_runner=health_runner,
        readme_runner=readme_runner,
        readme_enabled=dashboard_settings.enable_readme,
    )
    started = time.perf_counter()
    try:
        snapshot, cache_meta = await asyncio.wait_for(
            asyncio.to_thread(cache.get_or_load, key, loader, force=refresh == 1, deadline=deadline),
            timeout=dashboard_settings.scan_timeout_seconds + dashboard_settings.queue_timeout_seconds + 1.0,
        )
    except CacheBusyError as exc:
        _raise_api("DASHBOARD_BUSY", 429, "当前看板请求较多，请稍后重试")
    except (CacheTimeoutError, TimeoutError, asyncio.TimeoutError) as exc:
        _raise_api("DASHBOARD_TIMEOUT", 504, "扫描耗时过长，请稍后重试或缩小巡检范围")
    except SnapshotUnavailableError as exc:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用")
    except (RepoPathError, ApiError):
        raise
    except Exception as exc:
        LOGGER.exception("看板请求异常，request_id=%s", _request_id(request))
        _raise_api("INTERNAL_ERROR", 500, "服务处理请求时发生异常，请稍后重试")

    snapshot = dataclasses.replace(
        snapshot,
        repo=descriptor,
        snapshot=dataclasses.replace(
            snapshot.snapshot,
            cached=cache_meta.cached,
            cache_age_seconds=cache_meta.age_seconds,
            refresh_throttled=cache_meta.refresh_throttled,
            ttl_seconds=dashboard_settings.cache_ttl_seconds,
        ),
    )
    LOGGER.info(
        json.dumps(
            {
                "request_id": _request_id(request),
                "repo_label": descriptor.label,
                "repo_hash": key[:12],
                "cached": cache_meta.cached,
                "cache_age_seconds": cache_meta.age_seconds,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "scan_duration_ms": snapshot.snapshot.duration_ms,
                "status_code": 200,
                "error_code": None,
            },
            ensure_ascii=False,
        )
    )
    request.state.error_code = "OK"
    return snapshot


@router.get("/repos")
def repos(
    request: fastapi.Request,
    web_settings: object = fastapi.Depends(get_web_settings),
) -> starlette.responses.JSONResponse:
    from .service import list_repos

    if not web_settings.allowed_repo_roots:
        _raise_api("DASHBOARD_UNAVAILABLE", 503, "看板数据服务当前不可用", "未配置可用的仓库目录")
    descriptors = list_repos(web_settings)
    default = next((item.id for item in descriptors if item.is_default), None)
    return _json_response(
        request,
        {
            "repos": [to_dict(item) for item in descriptors],
            "default_repo": default,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        },
    )


@router.get("/overview")
async def overview(
    request: fastapi.Request,
    repo: str | None = fastapi.Query(default=None, max_length=512),
    refresh: int = fastapi.Query(default=0),
    web_settings: object = fastapi.Depends(get_web_settings),
    dashboard_settings: DashboardSettings = fastapi.Depends(get_dashboard_settings),
    cache: SnapshotCache = fastapi.Depends(get_cache),
    health_runner: Callable[..., object] = fastapi.Depends(get_health_runner),
    readme_runner: Callable[..., object] = fastapi.Depends(get_readme_runner),
) -> starlette.responses.JSONResponse:
    from .service import build_overview

    snapshot = await _prepare(request, repo, refresh, web_settings, dashboard_settings, cache, health_runner, readme_runner)
    return _json_response(request, to_dict(build_overview(snapshot)))


@router.get("/issues")
async def issues(
    request: fastapi.Request,
    repo: str | None = fastapi.Query(default=None, max_length=512),
    refresh: int = fastapi.Query(default=0),
    risk_level: str = fastapi.Query(default="all"),
    source_module: str = fastapi.Query(default="all"),
    keyword: str = fastapi.Query(default=""),
    page: int = fastapi.Query(default=1, ge=1, le=10000),
    page_size: int = fastapi.Query(default=20, ge=1, le=100),
    sort: str = fastapi.Query(default="risk_level"),
    order: str = fastapi.Query(default="asc"),
    web_settings: object = fastapi.Depends(get_web_settings),
    dashboard_settings: DashboardSettings = fastapi.Depends(get_dashboard_settings),
    cache: SnapshotCache = fastapi.Depends(get_cache),
    health_runner: Callable[..., object] = fastapi.Depends(get_health_runner),
    readme_runner: Callable[..., object] = fastapi.Depends(get_readme_runner),
) -> starlette.responses.JSONResponse:
    from .service import query_issues

    _validate_choice("risk_level", risk_level, _RISK_VALUES)
    _validate_choice("source_module", source_module, _SOURCE_VALUES)
    _validate_choice("sort", sort, _SORT_VALUES)
    _validate_choice("order", order, _ORDER_VALUES)
    if len(keyword) > dashboard_settings.max_keyword_length:
        _raise_api("INVALID_QUERY_PARAM", 400, "查询参数不合法", "字段：keyword")
    snapshot = await _prepare(request, repo, refresh, web_settings, dashboard_settings, cache, health_runner, readme_runner)
    page_result = query_issues(
        snapshot,
        risk_level=risk_level,
        source_module=source_module,
        keyword=keyword,
        page=page,
        page_size=page_size,
        sort_field=sort,
        order=order,
    )
    body = to_dict(page_result)
    body["charts"] = {
        "rule_breakdown": body.pop("rule_breakdown"),
        "module_risk_matrix": body.pop("module_risk_matrix"),
    }
    return _json_response(request, body)


@router.get("/structure")
async def structure(
    request: fastapi.Request,
    repo: str | None = fastapi.Query(default=None, max_length=512),
    refresh: int = fastapi.Query(default=0),
    web_settings: object = fastapi.Depends(get_web_settings),
    dashboard_settings: DashboardSettings = fastapi.Depends(get_dashboard_settings),
    cache: SnapshotCache = fastapi.Depends(get_cache),
    health_runner: Callable[..., object] = fastapi.Depends(get_health_runner),
    readme_runner: Callable[..., object] = fastapi.Depends(get_readme_runner),
) -> starlette.responses.JSONResponse:
    from .service import build_structure

    snapshot = await _prepare(request, repo, refresh, web_settings, dashboard_settings, cache, health_runner, readme_runner)
    return _json_response(request, to_dict(build_structure(snapshot)))
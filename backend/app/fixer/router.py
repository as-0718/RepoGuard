from __future__ import annotations

import asyncio

import fastapi
import starlette.responses

from ..api.settings import WebSettings

from . import paths, service
from .errors import (
    FIXER_INVALID_SELECTION,
    INTERNAL_ERROR,
    NOT_FOUND,
    PAYLOAD_TOO_LARGE,
    UNSUPPORTED_MEDIA_TYPE,
    VALIDATION_ERROR,
    raise_fixer,
)
from .schemas import ApplyRequest, PreviewRequest, RollbackRequest

MAX_BODY_BYTES = 2 * 1024 * 1024
router = fastapi.APIRouter(tags=["fixer"])


def get_web_settings(request: fastapi.Request) -> WebSettings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise_fixer(INTERNAL_ERROR, 500, "服务配置缺失")
    return settings


def require_desktop(settings: WebSettings = fastapi.Depends(get_web_settings)) -> WebSettings:
    if not settings.desktop_mode:
        raise_fixer(NOT_FOUND, 404, "请求的地址不存在")
    return settings


def require_json(request: fastapi.Request) -> None:
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().casefold() != "application/json":
        raise_fixer(UNSUPPORTED_MEDIA_TYPE, 415, "仅接受 application/json 请求")


def require_body_size(request: fastapi.Request) -> None:
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        length = int(raw)
    except ValueError:
        raise_fixer(VALIDATION_ERROR, 400, "Content-Length 不合法")
    if length > MAX_BODY_BYTES:
        raise_fixer(PAYLOAD_TOO_LARGE, 413, "请求体超过 2 MB")


def _request_id(request: fastapi.Request) -> str:
    return getattr(request.state, "request_id", "")


@router.post(
    "/preview",
    dependencies=[
        fastapi.Depends(require_desktop),
        fastapi.Depends(require_json),
        fastapi.Depends(require_body_size),
    ],
)
async def preview(
    payload: PreviewRequest,
    request: fastapi.Request,
    settings: WebSettings = fastapi.Depends(require_desktop),
) -> starlette.responses.JSONResponse:
    repo_root = await asyncio.to_thread(paths.resolve_repo, payload.repo, settings)
    result = await asyncio.to_thread(service.preview, repo_root, payload.issues, strict=payload.strict)
    return starlette.responses.JSONResponse(content=result, media_type="application/json; charset=utf-8")


@router.post(
    "/apply",
    dependencies=[
        fastapi.Depends(require_desktop),
        fastapi.Depends(require_json),
        fastapi.Depends(require_body_size),
    ],
)
async def apply(
    payload: ApplyRequest,
    request: fastapi.Request,
    settings: WebSettings = fastapi.Depends(require_desktop),
) -> starlette.responses.JSONResponse:
    repo_root = await asyncio.to_thread(paths.resolve_repo, payload.repo, settings)
    backup_dir = await asyncio.to_thread(paths.resolve_backup_dir, repo_root, payload.backup_dir)
    result = await asyncio.to_thread(
        service.apply,
        repo_root,
        backup_dir,
        payload.selections,
        on_stale=payload.on_stale,
        strict=payload.strict,
        request_id=_request_id(request),
    )
    return starlette.responses.JSONResponse(content=result, media_type="application/json; charset=utf-8")


@router.post(
    "/rollback",
    dependencies=[
        fastapi.Depends(require_desktop),
        fastapi.Depends(require_json),
        fastapi.Depends(require_body_size),
    ],
)
async def rollback(
    payload: RollbackRequest,
    request: fastapi.Request,
    settings: WebSettings = fastapi.Depends(require_desktop),
) -> starlette.responses.JSONResponse:
    repo_root = await asyncio.to_thread(paths.resolve_repo, payload.repo, settings)
    backup_dir = await asyncio.to_thread(paths.resolve_backup_dir, repo_root, payload.backup_dir)
    result = await asyncio.to_thread(
        service.rollback,
        repo_root,
        backup_dir,
        payload.backup_id,
        payload.backups,
        force=payload.force,
        strict=payload.strict,
        request_id=_request_id(request),
    )
    return starlette.responses.JSONResponse(content=result, media_type="application/json; charset=utf-8")
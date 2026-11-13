from __future__ import annotations

import json
import logging
import time
import uuid

import fastapi
import starlette.exceptions
import starlette.responses

from .models import HealthSnapshot, IngestOutcome, WebhookError
from .service import WebhookService
from .settings import WebhookConfig

LOGGER = logging.getLogger("repoguard.webhook.routes")


def _request_id(request: fastapi.Request) -> str:
    return getattr(request.state, "request_id", "")


def _header(request: fastapi.Request, name: str) -> str | None:
    target = name.casefold()
    for key, value in request.headers.items():
        if key.casefold() == target:
            return value
    return None


def error_response(
    request: fastapi.Request,
    code: str,
    status_code: int,
    message: str,
    detail: str | None = None,
) -> starlette.responses.JSONResponse:
    body = {
        "status": "rejected",
        "error": {"code": code, "message": message, "detail": detail},
        "request_id": _request_id(request),
    }
    return starlette.responses.JSONResponse(
        status_code=status_code,
        content=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Request-ID": _request_id(request),
            "X-Content-Type-Options": "nosniff",
        },
    )


def build_router(service: WebhookService, config: WebhookConfig) -> fastapi.APIRouter:
    router = fastapi.APIRouter()

    @router.post(config.path)
    async def receive(request: fastapi.Request) -> starlette.responses.JSONResponse:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            return error_response(request, "WEBHOOK_UNSUPPORTED_MEDIA_TYPE", 415, "请求内容类型必须是 application/json")
        if not config.enabled:
            return error_response(request, "WEBHOOK_DISABLED", 503, "Webhook 已禁用")
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                declared_length = int(declared)
            except ValueError:
                declared_length = 0
            if declared_length > config.max_body_bytes:
                return error_response(request, "WEBHOOK_PAYLOAD_TOO_LARGE", 413, "事件内容过大")
        if not config.secret.strip():
            return error_response(request, "WEBHOOK_SECRET_NOT_CONFIGURED", 503, "Webhook 签名密钥未配置")
        signature_value = _header(request, config.signature_header)
        if signature_value is None or not signature_value.strip():
            return error_response(request, "WEBHOOK_SIGNATURE_MISSING", 401, "缺少 Webhook 签名")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > config.max_body_bytes:
                return error_response(request, "WEBHOOK_PAYLOAD_TOO_LARGE", 413, "事件内容过大")
        raw_body = bytes(chunks)
        if config.sync_mode:
            outcome = service.handle_ingest_sync(raw_body, request.headers, _request_id(request))
        else:
            outcome = service.handle_ingest(raw_body, request.headers, _request_id(request))
        return starlette.responses.JSONResponse(
            status_code=outcome.status_code,
            content=outcome.body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
                "X-Request-ID": _request_id(request),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/healthz")
    def healthz() -> starlette.responses.JSONResponse:
        snapshot: HealthSnapshot = service.health_snapshot()
        body = {
            "status": snapshot.status,
            "service": snapshot.service,
            "version": snapshot.version,
            "secret_configured": snapshot.secret_configured,
            "signature_algorithm": snapshot.signature_algorithm,
            "openapi_mode": snapshot.openapi_mode,
            "engine": snapshot.engine,
            "queue_depth": snapshot.queue_depth,
            "queue_capacity": snapshot.queue_capacity,
            "dedup_size": snapshot.dedup_size,
            "allowed_repo_count": snapshot.allowed_repo_count,
            "recent_delivery_failures": snapshot.recent_delivery_failures,
            "time": snapshot.time,
        }
        return starlette.responses.JSONResponse(
            status_code=200 if snapshot.status == "ok" else 503,
            content=body,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return router


def install_middleware(app: fastapi.FastAPI, config: WebhookConfig) -> None:
    @app.middleware("http")
    async def context(request: fastapi.Request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - request.state.started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        try:
            LOGGER.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "openapi_mode": config.openapi_mode.value,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
        return response


def install_exception_handlers(app: fastapi.FastAPI) -> None:
    @app.exception_handler(WebhookError)
    async def webhook_error(request: fastapi.Request, exc: WebhookError):
        return error_response(request, exc.code, exc.status_code, exc.message, exc.detail)

    @app.exception_handler(starlette.exceptions.HTTPException)
    async def http_error(request: fastapi.Request, exc: starlette.exceptions.HTTPException):
        if exc.status_code == 405:
            return error_response(request, "METHOD_NOT_ALLOWED", 405, "请求方法不被支持")
        if exc.status_code == 404:
            return error_response(request, "NOT_FOUND", 404, "请求的地址不存在")
        return error_response(request, "WEBHOOK_HTTP_ERROR", exc.status_code, "请求无法处理")

    @app.exception_handler(Exception)
    async def internal_error(request: fastapi.Request, exc: Exception):
        LOGGER.exception("Webhook 未处理异常，request_id=%s", _request_id(request))
        return error_response(request, "WEBHOOK_INTERNAL_ERROR", 500, "Webhook 处理请求时发生异常")
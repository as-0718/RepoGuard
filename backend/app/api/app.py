from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from app.api.routes import (
    SERVICE_NAME,
    SERVICE_VERSION,
    ApiError,
    ReviewGate,
    router,
)
from app.api.schemas import error_payload
from app.api.security import RepoPathError
from app.api.settings import WebSettings, load_settings_from_env, normalize_settings, settings_summary
from app.dashboard.router import router as dashboard_router
from app.fixer.router import router as fixer_router
from app.storage import init_db

LOGGER = logging.getLogger("repoguard.api.app")

CSP_VALUE = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'"
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error_response(request: Request, code: str, status_code: int, message: str, detail: str | None = None) -> JSONResponse:
    request.state.error_code = code
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code, message, detail, _request_id(request)),
        headers={
            "X-Request-ID": _request_id(request),
            "Content-Type": "application/json; charset=utf-8",
        },
    )


def _configure_middleware(app: FastAPI, settings: WebSettings) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CSP_VALUE
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"

        log_record = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "error_code": getattr(request.state, "error_code", None),
            "duration_ms": duration_ms,
            "report_status": getattr(request.state, "report_status", None),
            "must_fix_count": getattr(request.state, "must_fix_count", None),
        }
        LOGGER.info(json.dumps(log_record, ensure_ascii=False))
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(request, exc.code, exc.status_code, exc.message, exc.detail)

    @app.exception_handler(RepoPathError)
    async def repo_path_error_handler(request: Request, exc: RepoPathError) -> JSONResponse:
        return _error_response(request, exc.code, exc.status_code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        detail = None
        if errors:
            location = errors[0].get("loc") or ()
            if location:
                detail = f"字段：{location[-1]}"
        return _error_response(request, "VALIDATION_ERROR", 422, "请求字段校验未通过", detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
            message = "该接口不支持当前请求方法"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
            message = "请求的地址不存在"
        else:
            code = "HTTP_ERROR"
            message = "请求无法处理"
        return _error_response(request, code, exc.status_code, message)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("未处理异常，request_id=%s", _request_id(request))
        return _error_response(request, "INTERNAL_ERROR", 500, "服务处理请求时发生异常，请稍后重试")


def _mount_static(app: FastAPI, settings: WebSettings) -> None:
    @app.get("/")
    def index() -> FileResponse:
        index_path = settings.static_dir / "index.html"
        if not index_path.is_file():
            raise ApiError("STATIC_NOT_FOUND", 503, "页面资源缺失，请检查部署")
        return FileResponse(index_path, media_type="text/html; charset=utf-8")

    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir), name="static")


def _configure_cors(app: FastAPI, settings: WebSettings) -> None:
    if not settings.cors_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )


def _build_lifespan(settings: WebSettings, gate: ReviewGate):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        summary = settings_summary(settings)
        LOGGER.info(
            "RepoGuard Web API 启动：监听 127.0.0.1:8000，允许根数量=%s，默认仓库=%s，被剔除根数量=%s",
            summary["allowed_repo_root_count"],
            summary["default_repo"],
            len(settings.allowed_repo_roots) - int(summary["allowed_repo_root_count"]),
        )
        try:
            try:
                init_db(settings.db_path)
            except Exception:
                LOGGER.exception("初始化数据库失败，历史记录功能将不可用")
            yield
        finally:
            gate.shutdown()

    return lifespan


def create_app(settings: WebSettings | None = None) -> FastAPI:
    effective_settings = normalize_settings(settings or load_settings_from_env())
    gate = ReviewGate(
        effective_settings.review_max_concurrency,
        effective_settings.review_timeout_seconds,
        effective_settings.queue_timeout_seconds,
    )
    app = FastAPI(
        title="RepoGuard Web API",
        version=SERVICE_VERSION,
        lifespan=_build_lifespan(effective_settings, gate),
    )
    app.state.settings = effective_settings
    app.state.review_gate = gate
    app.state.static_dir = effective_settings.static_dir

    _configure_middleware(app, effective_settings)
    _register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api/dashboard")
    app.include_router(fixer_router, prefix="/api/fixer")
    _mount_static(app, effective_settings)
    _configure_cors(app, effective_settings)
    return app


app = create_app()
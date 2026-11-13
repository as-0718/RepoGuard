from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore
from typing import Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from app.api.schemas import ReviewRequest, error_payload
from app.api.security import RepoPathError, resolve_repo_root
from app.api.settings import WebSettings, default_repo_root
from app.core.rules.common.models import CheckReport
from app.core.rules.common.report import report_to_dict

SERVICE_NAME: str = "repoguard-web-api"
SERVICE_VERSION: str = "1.0.0"
REVIEW_PATH: str = "/review"
HEALTH_PATH: str = "/health"
MAX_MANIFEST_BYTES: int = 2_097_152

LOGGER = logging.getLogger("repoguard.api.routes")
router = APIRouter()


class CheckRunner(Protocol):
    def __call__(
        self,
        manifest_text: str,
        repo_root: str | Path,
        config: "RuleConfig | None" = None,
    ) -> CheckReport: ...


class ApiError(Exception):
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


class ReviewGate:
    def __init__(
        self,
        max_concurrency: int,
        timeout_seconds: float,
        queue_timeout_seconds: float,
    ) -> None:
        self.max_concurrency = max_concurrency
        self.timeout_seconds = timeout_seconds
        self.queue_timeout_seconds = queue_timeout_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="repoguard-review",
        )
        self._semaphore = BoundedSemaphore(max_concurrency)
        self._shutdown = False

    async def run(
        self,
        runner: CheckRunner,
        manifest_text: str,
        repo_root: Path,
    ) -> CheckReport:
        acquired = await asyncio.to_thread(
            self._semaphore.acquire,
            True,
            self.queue_timeout_seconds,
        )
        if not acquired:
            raise ApiError("REVIEW_BUSY", 429, "当前检查请求较多，请稍后重试")

        try:
            future = self._executor.submit(runner, manifest_text, repo_root, None)
        except RuntimeError as exc:
            self._semaphore.release()
            raise ApiError("ENGINE_UNAVAILABLE", 503, "规则引擎当前不可用") from exc

        released = False

        def _release(_future: object) -> None:
            nonlocal released
            if not released:
                released = True
                self._semaphore.release()

        future.add_done_callback(_release)

        try:
            return await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=self.timeout_seconds,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise ApiError("REVIEW_TIMEOUT", 504, "检查耗时过长，请缩小变更清单后重试") from exc

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._executor.shutdown(wait=False, cancel_futures=False)


def get_settings(request: Request) -> WebSettings:
    return request.app.state.settings


def get_engine() -> CheckRunner:
    try:
        from app.core.rules.engine import run_check

        if not callable(run_check):
            raise ImportError("run_check 不可调用")
        return run_check
    except ImportError as exc:
        raise ApiError("ENGINE_UNAVAILABLE", 503, "规则引擎当前不可用") from exc


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _validation_detail(error: ValidationError) -> str:
    errors = error.errors()
    if not errors:
        return "请求字段校验未通过"
    location = errors[0].get("loc") or ()
    if location:
        return f"字段：{location[-1]}"
    return "请求字段校验未通过"


@router.post(REVIEW_PATH)
async def review(
    request: Request,
    settings: WebSettings = Depends(get_settings),
    runner: CheckRunner = Depends(get_engine),
) -> JSONResponse:
    request_id = _request_id(request)

    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            declared_size = int(declared_length)
        except ValueError:
            declared_size = 0
        if declared_size > settings.max_request_bytes:
            raise ApiError("REQUEST_TOO_LARGE", 413, "请求体过大，请缩小后重试")

    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        raise ApiError(
            "UNSUPPORTED_MEDIA_TYPE",
            415,
            "请求内容类型必须是 application/json",
        )

    body = await request.body()
    if len(body) > settings.max_request_bytes:
        raise ApiError("REQUEST_TOO_LARGE", 413, "请求体过大，请缩小后重试")

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError("INVALID_JSON", 400, "请求体不是合法的 JSON") from exc
    if not isinstance(data, dict):
        raise ApiError("INVALID_JSON", 400, "请求体顶层必须是 JSON 对象")

    try:
        payload = ReviewRequest.model_validate(data)
    except ValidationError as exc:
        raise ApiError(
            "VALIDATION_ERROR",
            422,
            "请求字段校验未通过",
            _validation_detail(exc),
        ) from exc

    manifest = payload.manifest
    if (
        len(manifest) > settings.max_manifest_chars
        or len(manifest.encode("utf-8")) > MAX_MANIFEST_BYTES
        or len(manifest.splitlines()) > settings.max_manifest_lines
    ):
        raise ApiError(
            "MANIFEST_TOO_LARGE",
            413,
            "变更清单过大，请缩小后重试",
            "请减少字符数、行数或文件体积",
        )

    if not settings.allowed_repo_roots:
        raise ApiError(
            "ENGINE_UNAVAILABLE",
            503,
            "规则引擎当前不可用",
            "未配置可用的仓库目录",
        )

    repo_real = resolve_repo_root(payload.repo, settings)

    gate: ReviewGate = request.app.state.review_gate
    try:
        report = await gate.run(runner, manifest, repo_real)
    except (ApiError, RepoPathError):
        raise
    except Exception as exc:
        LOGGER.exception("规则引擎执行异常，request_id=%s", request_id)
        raise ApiError("INTERNAL_ERROR", 500, "检查执行失败，请稍后重试") from exc

    try:
        content = report_to_dict(report)
    except Exception as exc:
        LOGGER.exception("检查报告序列化失败，request_id=%s", request_id)
        raise ApiError("INTERNAL_ERROR", 500, "检查结果无法返回，请稍后重试") from exc

    request.state.report_status = report.status.value
    request.state.must_fix_count = report.summary.must_fix_count
    request.state.error_code = "OK"

    response = JSONResponse(status_code=200, content=content)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get(HEALTH_PATH)
def health(
    request: Request,
    settings: WebSettings = Depends(get_settings),
) -> JSONResponse:
    from datetime import datetime, timezone

    try:
        from app.core.rules.engine import run_check

        engine_available = callable(run_check)
    except Exception:
        engine_available = False

    default_root = default_repo_root(settings)
    healthy = engine_available and bool(settings.allowed_repo_roots) and default_root is not None
    payload = {
        "status": "ok" if healthy else "degraded",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "engine": "available" if engine_available else "unavailable",
        "default_repo": settings.default_repo,
        "allowed_repo_root_count": len(settings.allowed_repo_roots),
        "time": datetime.now(timezone.utc).isoformat(),
    }
    response = JSONResponse(status_code=200 if healthy else 503, content=payload)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response
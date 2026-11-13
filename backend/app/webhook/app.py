from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

import fastapi

from ..api.settings import WebSettings, load_settings_from_env
from ..integrations.openapi import OpenApiAdapter
from .routes import build_router, install_exception_handlers, install_middleware
from .service import EngineRunner, WebhookService
from .settings import WebhookConfig, config_summary, load_webhook_config, normalize_config

SERVICE_NAME: str = "repoguard-webhook"
SERVICE_VERSION: str = "1.0.0"
LOGGER = logging.getLogger("repoguard.webhook.app")


def create_webhook_app(
    config: WebhookConfig | None = None,
    *,
    service: WebhookService | None = None,
    web_settings: WebSettings | None = None,
    runner: EngineRunner | None = None,
    adapter: OpenApiAdapter | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> fastapi.FastAPI:
    effective = normalize_config(config or load_webhook_config())
    settings = web_settings or load_settings_from_env()
    webhook_service = service or WebhookService(
        effective,
        settings,
        runner=runner,
        adapter=adapter,
        clock=clock,
        sleeper=sleeper,
    )

    @contextlib.asynccontextmanager
    async def lifespan(application: fastapi.FastAPI):
        summary = config_summary(effective)
        LOGGER.info(
            "RepoGuard Webhook 启动：监听 %s:%s，路径=%s，签名算法=HMAC-SHA256，OpenAPI 模式=%s，允许仓库数=%s，队列容量=%s，签名密钥=%s，OpenAPI 令牌=%s",
            effective.host,
            effective.port,
            effective.path,
            effective.openapi_mode.value,
            len(settings.allowed_repo_roots),
            effective.queue_capacity,
            "已配置" if summary["secret_configured"] else "未配置",
            "已配置" if summary["token_configured"] else "未配置",
        )
        webhook_service.start()
        try:
            yield
        finally:
            webhook_service.shutdown(effective.stop_timeout_seconds)

    application = fastapi.FastAPI(
        title="RepoGuard Webhook",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )
    application.state.webhook_config = effective
    application.state.webhook_service = webhook_service
    install_middleware(application, effective)
    install_exception_handlers(application)
    application.include_router(build_router(webhook_service, effective))
    return application


app = create_webhook_app()

__all__: tuple[str, ...] = ("create_webhook_app", "app")
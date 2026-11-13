from __future__ import annotations

from typing import Any

from .models import (
    AuthScheme,
    CommentPayloadLike,
    OpenApiConfigError,
    OpenApiError,
    OpenApiMode,
    OpenApiProfile,
    PublishResult,
)

__all__: tuple[str, ...] = (
    "OpenApiAdapter",
    "ConfigurableOpenApiAdapter",
    "OpenApiProfile",
    "OpenApiMode",
    "AuthScheme",
    "PublishResult",
    "CommentPayloadLike",
    "OpenApiError",
    "OpenApiConfigError",
)


def __getattr__(name: str) -> Any:
    if name in {"OpenApiAdapter", "ConfigurableOpenApiAdapter"}:
        from .openapi import ConfigurableOpenApiAdapter, OpenApiAdapter

        globals().update(
            {
                "OpenApiAdapter": OpenApiAdapter,
                "ConfigurableOpenApiAdapter": ConfigurableOpenApiAdapter,
            }
        )
        return globals()[name]
    raise AttributeError(f"模块 app.integrations 没有属性 {name}")
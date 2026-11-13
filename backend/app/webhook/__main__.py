from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

import uvicorn

from .app import create_webhook_app
from .settings import load_webhook_config

LOGGER = logging.getLogger("repoguard.webhook.main")


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    config = load_webhook_config()
    application = create_webhook_app(config)
    if config.host == "0.0.0.0":
        LOGGER.warning("Webhook 已对外暴露，必须由反向代理提供 TLS 与访问控制")
    try:
        uvicorn.run(
            application,
            host=config.host,
            port=config.port,
            log_level=config.log_level.lower(),
        )
    except OSError:
        LOGGER.error("Webhook 监听失败：端口可能已被占用，请更换端口或释放占用")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
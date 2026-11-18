"""桌面壳专用后端入口。

由 Electron 壳在启动时拉起，解析 host/port 后直接运行 FastAPI app 对象。
样本仓库、前端静态目录、数据库路径均通过环境变量传入（见 desktop/main/backend-process.js）。
"""
from __future__ import annotations

import argparse

import uvicorn

from app.api.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="RepoGuard 桌面后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

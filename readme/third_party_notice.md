# 开源组件说明（Third-Party Notice）

本项目自身基于 **MIT License** 开源（见仓库根目录 `LICENSE`）。以下列出项目直接使用的第三方开源组件及其许可证，许可证依据各组件官方仓库 `LICENSE` 与 npm / PyPI 元数据核实。

## 后端直接依赖

| 组件 | 版本 | 用途 | 许可证 | 来源 |
|---|---|---|---|---|
| fastapi | 0.115.6 | Web API 框架 | MIT | https://github.com/fastapi/fastapi |
| uvicorn | 0.34.0 | ASGI Web 服务器 | BSD-3-Clause | https://github.com/Kludex/uvicorn |
| httpx | 0.28.1 | HTTP 客户端（仅供 Web API 测试的 TestClient 使用） | BSD-3-Clause | https://github.com/encode/httpx |

## 前端直接依赖

| 组件 | 版本 | 用途 | 许可证 | 来源 |
|---|---|---|---|---|
| vue | 3.5.45 | 视图框架 | MIT | https://github.com/vuejs/core |
| vue-router | 4.6.4 | 前端路由 | MIT | https://github.com/vuejs/router |
| echarts | 6.1.0 | 图表可视化 | Apache-2.0 | https://github.com/apache/echarts |
| vite | 8.3.6 | 前端构建与开发服务器 | MIT | https://github.com/vitejs/vite |
| @vitejs/plugin-vue | 6.0.10 | Vue 单文件组件支持插件 | MIT | https://github.com/vitejs/vite-plugin-vue |

## 桌面壳直接依赖（`desktop/package.json`，仅打包便携包需要）

| 组件 | 版本 | 用途 | 许可证 | 来源 |
|---|---|---|---|---|
| electron | 45.3.3 | 桌面应用运行时与窗口壳（内嵌 Chromium 与 Node 运行时） | MIT | https://github.com/electron/electron |
| electron-builder | 26.18.0 | Windows 便携包打包工具 | MIT | https://github.com/electron-userland/electron-builder |

## 传递依赖说明

- fastapi 的传递依赖（如 starlette、pydantic 等）随各自原始许可证一并分发，未在本项目中直接修改。
- Electron 内嵌的 Chromium 与 Node 运行时按其原始许可证随 Electron 分发；便携包中保留 Electron 自带的 `LICENSES.chromium.html`。
- 规则引擎、全仓巡检、README 目录生成与命令行工具仅使用 Python 标准库，无第三方运行时依赖。

## 许可证要点（便于合规理解）

- **MIT**：允许使用、复制、修改、合并、发布、分发与再销售，只需在副本中保留版权与许可声明；按「现状」提供，不提供担保。
- **BSD-3-Clause**：在 MIT 类宽松条款基础上，禁止用版权方名义为衍生产品背书。
- **Apache-2.0**：宽松许可，另包含专利授权条款；分发时需保留许可证、声明修改与 NOTICE 等文件。

> 如对某组件许可证条款有正式合规用途，请以其官方仓库 `LICENSE` 文件为准。

# RepoGuard 作品说明文档

## 项目简介

RepoGuard 是面向课程学习与科创社团共享仓库的离线自检工具：对一次变更清单或整个仓库执行命名、代码、链接、敏感信息等检查，输出分级报告，并提供 Web API、可视化看板与 Windows 桌面应用。日常巡检与看板为只读；修复动作集中在独立的 fixer 层，仅对白名单规则做“先备份、预览 diff、勾选写入、可回滚”的选择性修复，不做一键全改。

## 本目录文档索引

| 文件 | 对应要求 | 内容 |
|---|---|---|
| `environment.md` | 环境依赖说明 | 运行时版本、后端/前端/桌面壳第三方依赖、测试基线 |
| `install.ps1` / `install.sh` | 一键安装脚本 | Windows / Linux 安装后端与前端依赖（不自动跑测试） |
| `deployment.md` | 部署运行步骤 | 命令行、Web 看板、桌面便携包三种运行方式、安全边界与事实声明 |
| `third_party_notice.md` | 开源组件说明 | 第三方组件版本、用途、许可证与来源 |
| `codearts_summary.md` | 码道应用总结 | 门禁式协作模式、AI 作用、测试演进与证据索引 |
| `docs/rules_engine_usage.md` | 规则引擎说明 | 变更清单格式、汇总入口、报告阅读、退出码与配置项 |
| `docs/repo_health_readme_usage.md` | 全仓巡检与 README 生成说明 | 健康巡检命令、僵尸判定口径、README 目录索引与差异对比 |
| `docs/dashboard_deploy_usage.md` | 看板部署与接口说明 | 视图路由、只读看板接口、历史快照与修复事件接口、安全边界 |
| `docs/web_api_usage.md` | Web API 说明 | 旧 `/api/review` 检查接口、仓库白名单配置、错误码与验收 |
| `docs/webhook_openapi_usage.md` | Webhook 与 OpenAPI 说明 | 验签机制、入站/出站环境变量、三种出站模式与错误码 |
| `docs/fixer_usage.md` | 修复辅助层说明 | fixer 边界、备份目录、diff 预览、写入与回滚、错误码与限制 |

## 快速开始

### Windows 桌面便携包（最省事，无需装 Python / Node）

从 GitHub Release 下载 `RepoGuard-win-x64.zip`，解压后运行 `RepoGuard.exe`，在选仓库界面选择待巡检的本地目录即可。

### 命令行巡检（最轻量，无需第三方依赖）

```bash
cd backend
python -m app.health.cli --repo ../demo-repo --format text
```

### 本地启动 Web 看板

```bash
# 后端（8000）
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
# 前端（5173，另开窗口）
cd frontend && npm run dev
```

## 功能一览

- **规则引擎**：命名与目录、代码写法、Markdown 链接、敏感信息与大文件四类检查，分「必须修改 / 优化建议」两级；代码写法覆盖注释完整性、危险函数 / 命令注入、调试残留与常见 bug 模式（可变对象默认参数、`None` 身份比较、空函数体）。
- **全仓健康巡检**：递归扫描，统计文件数、Markdown / 代码文件数、Demo 工程，汇总问题与高风险数，识别僵尸候选与无法判定项。
- **README 目录生成**：扫描文档与 Demo 工程，生成索引并与现有 README 做差异对比。
- **可视化看板**：概览指标、问题列表、仓库结构；多次扫描结果留存为历史快照，历史页可回看对比、展示累计巡查次数与修复 / 回滚成功失败案例。
- **选择性修复（fixer）**：仅白名单 `link-005`（链接空格编码）、`code-012`（`== None`→`is None`）、`code-010`（调试断点注释化），先备份、预览 diff、逐条勾选、可回滚；非白名单只给只读建议。
- **Windows 桌面壳**：Electron 拉起本地后端，提供须知页、目录选择与桌面窗口看板；深色默认、深浅一键切换。

## 团队信息

- 队伍名称：云珩智联
- 成员：安栩锐、邹雅雯、黄泓博
- 版本号：v1.1.0
- 联系邮箱：shuaia433@gmail.com
- 代码仓库：https://github.com/as-0718/RepoGuard

## 提交包结构对照

| 目录 | 内容 |
|---|---|
| `ppt/` | 作品整体介绍 PPT / PDF（场景背景、功能架构、核心亮点、码道应用说明） |
| `project/` | 可演示完整功能的作品 Demo 源码 |
| `video/` | 演示脚本与命令清单（`demo-commands.txt`，按步骤复现看板与修复流程；本轮不出成片） |
| `codearts_proof/` | 码道使用证明：AI 交互记录、生成/重构/排错记录、阶段截图 |
| `readme/` | 本目录：环境依赖、安装脚本、部署步骤、开源组件说明、码道总结 |

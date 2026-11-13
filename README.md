# RepoGuard

面向课程学习与科创社团共享仓库的**只读离线自检工具**：对一次变更清单或整个仓库执行命名、代码、链接、敏感信息等检查，输出分级报告，并提供 Web API 与可视化看板。工具不联网、不执行被扫描代码、不自动修复。

## 功能特性

- **规则引擎**：命名与目录、代码注释与写法、Markdown 链接、敏感信息与大文件四类检查；问题分「必须修改 / 优化建议」两级。
- **全仓健康巡检**：递归扫描仓库，统计文件数、Markdown / 代码文件数、Demo 工程，汇总问题数与高风险数，并识别僵尸候选、无法判定项与降级项。
- **README 目录生成**：扫描 Markdown 与 Demo 工程，生成目录索引，并与现有 README 做差异对比（不直接改写 README）。
- **Web API + 单页控制台**：FastAPI 提供只读检查接口与健康检查。
- **可视化看板**：Vue 3 + ECharts 展示概览指标、问题列表与仓库结构。
- **Webhook + OpenAPI 回写**：支持离线可测的事件回写与幂等处理。

## 技术栈

- 后端：Python 3.10+，FastAPI、Uvicorn；规则引擎、巡检与 CLI 仅使用 Python 标准库。
- 前端：Vue 3、Vue Router、ECharts，Vite 构建。
- 测试：Python unittest（基线 438 项通过，4 项跳过）。

## 目录结构

```
RepoGuard/
├── backend/            # 后端服务与规则、巡检、CLI 模块
│   └── app/
│       ├── api/        # Web API 与单页控制台
│       ├── core/rules/ # 规则引擎
│       ├── health/     # 全仓健康巡检
│       ├── readme/    # README 目录生成
│       ├── webhook/    # Webhook 与 OpenAPI 回写
│       ├── integrations/
│       └── shared/
├── frontend/          # Vue 3 + ECharts 看板
├── docs/              # 各模块使用说明
├── deploy/            # 容器、systemd、nginx、定时任务等部署产物
├── demo-repo/         # 内置示例仓库（含规则测试样本）
├── codearts_proof/    # 码道（CodeArts）开发过程证据
└── scripts/           # 工程校验脚本
```

## 环境要求

- Python ≥ 3.10（规则 / 巡检 / CLI 无需第三方依赖）
- Node ≥ 22.12（仅前端构建与看板需要）

## 快速开始

### 命令行全仓巡检（最轻量，无需安装第三方依赖）

```bash
cd backend
python -m app.health.cli --repo ../demo-repo --format text
```

### 启动 Web API

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

访问：单页控制台 `http://127.0.0.1:8000/`，健康检查 `http://127.0.0.1:8000/api/health`。

### 启动前端看板（开发模式）

```bash
cd frontend
npm ci
npm run dev
```

## 命令行工具

| 用途 | 命令 |
|---|---|
| 规则引擎（按变更清单检查） | `python -m app.core.rules.engine --manifest <清单文件> --repo <仓库根目录>` |
| 全仓健康巡检 | `python -m app.health.cli --repo <仓库根目录>` |
| README 目录生成 | `python -m app.readme.cli --repo <仓库根目录>` |

变更清单每行格式为「状态 + 空格 + 文件路径」，状态 `A` 新增、`M` 修改、`D` 删除；也可用 `git diff --name-status` 导出后另存为 UTF-8 文本。

## 运行测试

```bash
cd backend
python -m unittest discover -s tests -t .
```

## 文档

- `docs/rules_engine_usage.md`：规则引擎用法
- `docs/repo_health_readme_usage.md`：全仓巡检与 README 目录
- `docs/web_api_usage.md`：Web API 用法
- `docs/webhook_openapi_usage.md`：Webhook 与 OpenAPI 回写
- `docs/dashboard_deploy_usage.md`：看板与部署说明
- `deploy/README.md`：服务器 / 容器部署手册

## 说明

- `demo-repo/` 中出现的弱口令、示例令牌（如 `123456`、`ghp_abc...`）均为**规则检测用的测试样本，不是真实凭证**。
- 本工具只读离线运行：不联网请求外链、不执行被扫描代码、不使用 `eval`/`exec`、不修改被巡检仓库。
- 白名单：Web 层仅读取 `REPOGUARD_ALLOWED_REPOS` 配置内的仓库目录，请求参数不能覆盖该配置。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

**团队**：云珩智联（安栩锐、邹雅雯、黄泓博）

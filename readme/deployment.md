# 部署运行步骤

## 一、三种运行方式

### 1. Windows 桌面便携包（演示首选）

从 GitHub Release 下载 `RepoGuard-win-x64.zip`，解压到本地任意目录，运行 `RepoGuard.exe` 即可。便携包已内置后端运行时、前端页面与示例仓库，本机无需安装 Python 或 Node；首次启动自动创建空的本地数据库，在选仓库界面选择待巡检目录后开始扫描。

### 2. 本地开发 / Web 看板

#### 安装依赖

一键脚本（只安装依赖，不自动跑测试）：

- Windows PowerShell：

  ```powershell
  powershell -ExecutionPolicy Bypass -File readme/install.ps1
  ```

- Linux / macOS：

  ```bash
  bash readme/install.sh
  ```

手动等价步骤：后端创建虚拟环境并安装 `backend/requirements.txt`；前端在 `frontend/` 执行 `npm ci`。

#### 命令行全仓巡检（最轻量，无需第三方依赖）

```bash
cd backend
python -m app.health.cli --repo ../demo-repo --format text
```

#### 启动 Web API

```bash
cd backend
# Windows
.\.venv\Scripts\python.exe -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
# Linux / macOS
# .venv/bin/python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

- 单页控制台：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/api/health`

#### 启动前端看板（开发模式）

```bash
cd frontend
npm run dev
```

看板默认 `http://127.0.0.1:5173/`，`/api` 代理到后端 8000 端口。

## 二、命令行工具

| 用途 | 命令（工作目录 `backend/`） |
|---|---|
| 规则引擎（按变更清单检查） | `python -m app.core.rules.engine --manifest <清单文件> --repo <仓库根目录>` |
| 全仓健康巡检 | `python -m app.health.cli --repo <仓库根目录>` |
| README 目录生成 | `python -m app.readme.cli --repo <仓库根目录>` |

## 三、生产上线（摘要）

完整手册见 `deploy/README.md`。前置条件：Python ≥ 3.10、nginx、systemd、低权限运行用户与独立目录。

上线步骤：

1. 同步代码到部署目录，确认 `deploy/.env` 未入库；
2. 由 `deploy/env.example` 复制配置，填写 `REPOGUARD_ALLOWED_REPOS`、`REPOGUARD_DEFAULT_REPO`、`REPOGUARD_WEBHOOK_SECRET`；
3. 创建后端虚拟环境并安装依赖；
4. 安装并启用 systemd 服务（API、webhook）；
5. 构建前端并投放 `frontend/dist/` 到 nginx 静态目录；
6. 配置 nginx 反向代理，`nginx -t` 后 reload；
7. 执行冒烟脚本校验健康检查与看板接口；
8. 按需配置每日定时巡检（cron / Windows 计划任务 / CodeArts 流水线，三选一，禁止并发）。

可选容器路径：`docker compose -f deploy/docker-compose.yml up -d --build`（需目标机具备 Docker）。

## 四、安全与运行边界

- API 与 webhook 仅监听 `127.0.0.1`（8000 / 8010），禁止映射为 `0.0.0.0` 公网监听；
- Web 层仅读取 `REPOGUARD_ALLOWED_REPOS` 配置内的仓库目录，请求参数不能覆盖该配置；
- 巡检结论与看板接口保持只读；历史快照与修复 / 回滚事件存本地 SQLite，用于回看多次扫描结果、累计巡查次数与成功失败案例；
- 修复动作仅出现在 fixer 层白名单规则（`link-005`、`code-012`、`code-010`）范围内：先在仓库外备份、预览 diff、勾选确认后才写入，并支持本次会话内回滚；不做一键全改、不做 git 自动提交；
- 缓存为进程内存，仅支持单实例。

## 五、事实声明（如实记录）

开发本机无 Docker、nginx、hcloud（云 CLI）、crontab。本仓库内的部署与定时产物**仅做过静态校验**，未执行 `docker build`、`docker compose config`、`nginx -t`、systemd 启动、计划任务注册、cron 安装，也未上云；CodeArts 流水线 YAML 的 schema 未核实，以控制台可视化配置为准。

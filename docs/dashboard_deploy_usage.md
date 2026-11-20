# RepoGuard 只读看板使用说明

> 面向首次使用者的看板功能、API、缓存与巡检说明。部署与上线步骤见 [`deploy/README.md`](../deploy/README.md)。

---

## 1. 看板功能与四视图

看板聚合当前仓库的巡检快照，巡检结论与看板接口保持**只读**、不写仓库；多次巡检快照与修复 / 回滚事件落本地 SQLite，供历史页回看；**无用户体系**；写操作只出现在桌面版 fixer 白名单范围内。

| 视图 | 路径 | 主要内容 | 交互 |
|---|---|---|---|
| 总览 | `/overview` | 文件数、问题总数、高风险/建议、僵尸候选、无法判定、降级项、跳过文件、扫描耗时；风险构成、来源模块、文件类型、问题最多文件 | KPI 与扇区/条形可跳转到问题明细；支持刷新 |
| 问题明细 | `/issues` | 筛选后总数、高风险、建议；规则 Top10、模块×风险堆叠图；问题表 | 风险/模块/关键词筛选、排序、分页、行展开看建议与片段 |
| 结构 / README | `/structure` | 文档数、Demo 确认/疑似、README 与目录区块状态、差异数；分区/ Demo / 差异图；差异、Demo、无法判定项表 | 差异类型点击本地过滤；README 索引纯文本预览 |
| 历史 | `/history` | 历次巡检快照列表与累计巡查次数；点击快照回看当时结论；修复 / 回滚成功失败案例及涉及文件 | 按仓库筛选；快照点开看明细；案例展示结果、计数与备份路径 |
| 关于 / 健康 | `/about` | API 状态、引擎可用性、缓存年龄；模块风险热力图；错误码矩阵；版本与配置摘要 | 只读；健康接口 503 时显示降级/不可用 |

**状态同步**：筛选、排序、分页、关键词写入 URL 查询参数，刷新页面可恢复；切换仓库保留当前视图并重置分页。

**三态**：首次加载显示骨架屏；空数据显示空态；请求失败且无旧数据显示错误面板，有旧数据时保留旧数据并提示"可能已过期"。

---

## 2. 快速开始

### 2.1 开发场景（不写系统）

后端（在 `backend/` 下，使用已安装依赖的解释器）：

```bash
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

前端（在 `frontend/` 下）：

```bash
npm ci
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`，Vite 将 `/api` 代理到 `127.0.0.1:8000`。

### 2.2 本地预览构建产物

```bash
cd frontend
npm ci
npm run build
```

用任意本地静态服务器指向 `frontend/dist/`；由于使用 history 路由，未知路径需回退到 `index.html`（nginx 配置已提供 `try_files`）。

### 2.3 环境要求

- Node ≥ 22.12（本机实测 v24.19.0 / npm 11.17.0；用户口径为 v22.23.2 / 10.9.8）
- 后端依赖见 `backend/requirements.txt`，本阶段零新增依赖
- 看板缓存为单进程内存，多实例不共享

### 2.4 选择仓库

页面顶部下拉框来自 `/api/dashboard/repos`。默认仓库由服务端 `REPOGUARD_DEFAULT_REPO` 决定；未选择时自动使用默认仓库。

---

## 3. API 参数与响应示例

上表接口均为 `GET`，只读，响应 `Cache-Control: no-store`。

### 3.1 接口与参数

| 接口 | 参数 | 说明 |
|---|---|---|
| `/api/dashboard/repos` | 无 | 返回可见仓库与默认仓库，不暴露绝对路径 |
| `/api/dashboard/overview` | `repo`（可选，≤512）、`refresh`（0/1） | 总览快照 |
| `/api/dashboard/issues` | `repo`、`refresh`、`risk_level`（`all/high/suggestion`）、`source_module`（模块名或 `all`）、`keyword`（≤64）、`page`（≥1）、`page_size`（1–100）、`sort`（`risk_level/file_path/line_no/rule_id/source_module/message`）、`order`（`asc/desc`） | 分页问题明细与图表 |
| `/api/dashboard/structure` | `repo`、`refresh` | README/结构投影 |
| `/api/dashboard/history` | `repo`（可选）、`limit`（1–200，默认 20） | 历次巡检快照列表与 `total_count`（累计巡查次数） |
| `/api/dashboard/history/{snapshot_id}` | 路径 `snapshot_id` | 单个快照明细及其问题；不存在返回 `HISTORY_NOT_FOUND` 404 |
| `/api/dashboard/fix-events` | `repo`（可选，按仓库标识）、`limit`（1–200，默认 20） | 修复 / 回滚事件：动作、结果、成功/跳过/回滚/失败计数、涉及文件清单（`path` 与 `mtime`）、耗时、请求 ID |
| `/api/health` | 无 | 既有健康接口；降级时返回 503 |

### 3.2 响应示例（脱敏）

`/api/dashboard/repos`：

```json
{
  "repos": [{ "id": "demo-repo", "label": "demo-repo", "is_default": true }],
  "default_repo": "demo-repo",
  "generated_at": "2026-01-01T00:00:00+00:00"
}
```

`/api/dashboard/overview?repo=demo-repo`（节选）：

```json
{
  "repo": { "id": "demo-repo", "label": "demo-repo", "is_default": true },
  "snapshot": {
    "status": "正常",
    "scanned_at": "2026-01-01T02:00:00+00:00",
    "duration_ms": 1200,
    "cached": true,
    "cache_age_seconds": 12,
    "refresh_throttled": false,
    "ttl_seconds": 60,
    "degraded": [],
    "warnings": []
  },
  "summary": {
    "issue_count": 12,
    "must_fix_count": 3,
    "suggestion_count": 9,
    "zombie_candidate_count": 1,
    "undetermined_count": 0,
    "skipped_file_count": 0,
    "degraded_count": 0
  },
  "charts": {
    "risk_breakdown": { "high": 3, "suggestion": 9 },
    "module_breakdown": [{ "module": "代码检查", "count": 7 }],
    "file_type_breakdown": [{ "type": "markdown", "count": 4 }],
    "top_files": [{ "file_path": "docs/README.md", "issue_count": 2 }]
  },
  "files_count": 18
}
```

`/api/dashboard/issues?repo=demo-repo&page=1&page_size=20`（节选）：

```json
{
  "items": [
    {
      "file_path": "docs/README.md",
      "line_no": 12,
      "rule_id": "naming-001",
      "source_module": "命名与目录检查",
      "risk_level": "建议",
      "message": "文件命名建议使用小写短横线",
      "suggestion": "将文件名改为小写短横线形式",
      "excerpt": "相关片段已脱敏"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 12,
  "total_pages": 1,
  "counts": { "total": 12, "high": 3, "suggestion": 9 },
  "charts": {
    "rule_breakdown": [{ "rule_id": "naming-001", "count": 4 }],
    "module_risk_matrix": [{ "module": "代码检查", "high": 2, "suggestion": 5 }]
  }
}
```

`/api/dashboard/structure?repo=demo-repo`（节选）：

```json
{
  "readme": {
    "status": "正常",
    "format_version": "1.0",
    "document_count": 4,
    "demo_project_count": 1,
    "demo_project_suspected_count": 1,
    "readme_found": true,
    "toc_block_found": true,
    "diffs": [
      {
        "change_type": "新增",
        "path": "docs/new-guide.md",
        "old_title": null,
        "new_title": "新手指南",
        "old_position": null,
        "new_position": 3
      }
    ],
    "undetermined": [],
    "degraded": [],
    "warnings": [],
    "index_markdown": "## 文档索引\n- [使用说明](docs/usage.md)"
  },
  "index": {
    "document_section": { "name": "文档索引", "items": [] },
    "demo_section": { "name": "Demo 工程", "items": [] }
  },
  "demo": { "confirmed_items": [], "suspected_count": 1 }
}
```

`/api/dashboard/history?repo=demo-repo`（节选）：

```json
{
  "history": [
    {
      "id": 12,
      "repo_label": "demo-repo",
      "repo_key": "…",
      "scanned_at": "2026-01-01T02:00:00+00:00",
      "duration_ms": 1200,
      "files_count": 18,
      "issue_count": 12,
      "must_fix_count": 3,
      "suggestion_count": 9,
      "zombie_count": 1,
      "undetermined_count": 0,
      "status": "正常",
      "created_at": "2026-01-01T02:00:00+00:00"
    }
  ],
  "total_count": 12,
  "generated_at": "2026-01-01T02:05:00+00:00"
}
```

`/api/dashboard/history/12`（节选）：

```json
{
  "snapshot": {
    "id": 12,
    "repo_label": "demo-repo",
    "scanned_at": "2026-01-01T02:00:00+00:00",
    "status": "正常",
    "issues": [
      {
        "file_path": "docs/README.md",
        "line_no": 12,
        "rule_id": "naming-001",
        "source_module": "命名与目录检查",
        "risk_level": "建议",
        "message": "文件命名建议使用小写短横线",
        "suggestion": "将文件名改为小写短横线形式"
      }
    ]
  }
}
```

`/api/dashboard/fix-events?repo=demo-repo`（节选）：

```json
{
  "events": [
    {
      "id": 5,
      "created_at": "2026-01-01T02:10:00+00:00",
      "repo_label": "demo-repo",
      "action": "apply",
      "result": "applied=2 skipped=0",
      "applied_count": 2,
      "skipped_count": 0,
      "restored_count": 0,
      "failed_count": 0,
      "files": [
        { "path": "lab/uart.c", "mtime": "2026-01-01T02:10:00+00:00" }
      ],
      "duration_ms": 86,
      "request_id": "req-…"
    }
  ],
  "generated_at": "2026-01-01T02:11:00+00:00"
}
```

### 3.3 错误码

| code | HTTP | 前端提示 |
|---|---|---|
| `INVALID_QUERY_PARAM` | 400 | 查询参数不合法，请检查筛选条件 |
| `INVALID_REPO_PATH` | 400 | 仓库路径格式不合法 |
| `REPO_FORBIDDEN` | 403 | 仓库路径不在服务端允许范围内 |
| `REPO_NOT_FOUND` | 404 | 仓库目录不存在或不可用 |
| `METHOD_NOT_ALLOWED` | 405 | 该接口不支持当前请求方法 |
| `VALIDATION_ERROR` | 422 | 请求字段校验未通过 |
| `DASHBOARD_BUSY` | 429 | 当前看板请求较多，请稍后重试 |
| `DASHBOARD_UNAVAILABLE` | 503 | 看板数据服务当前不可用 |
| `DASHBOARD_TIMEOUT` | 504 | 扫描耗时过长，请稍后重试或缩小巡检范围 |
| `INTERNAL_ERROR` | 500 | 服务处理请求时发生异常，请稍后重试 |
| `STATIC_NOT_FOUND` | 404 | 页面资源缺失，请检查部署 |

错误响应结构：`{ "error": { "code": "...", "message": "...", "detail": "..." }, "request_id": "..." }`，不含堆栈与绝对路径。

---

## 4. 缓存语义

| 项 | 规则 |
|---|---|
| 缓存位置 | API 进程内；单实例，多实例不共享 |
| TTL | 默认 60 秒；过期后下次请求回源扫描 |
| 容量 | LRU，默认 8 个仓库 |
| 单飞 | 同一仓库并发请求只触发一次扫描 |
| 跨仓库并发 | 默认 2；排队超过 5 秒返回 429 |
| 强制刷新 | `refresh=1`；最小间隔 10 秒，过频触发节流并返回最近快照 |
| 扫描超时 | 默认 30 秒，返回 504；晚到结果丢弃且不写缓存 |
| 失败缓存 | 失败结果不缓存 |
| HTTP 缓存 | 响应 `Cache-Control: no-store`，浏览器不缓存 |

---

## 5. 部署入口

部署产物、端口规划、本地校验与上线步骤统一见 [`deploy/README.md`](../deploy/README.md)。

当前环境无 Docker、nginx、hcloud，部署产物只做过静态校验；**未真实构建、未上云**。

---

## 6. 定时巡检

### 6.1 三种方式（三选一，禁止并发）

| 方式 | 入口 | 触发 |
|---|---|---|
| Linux cron | `deploy/cron/repoguard-daily.cron` | 02:00 健康 / 02:05 README / 02:10 清理 |
| Windows 计划任务 | `deploy/schedule/register_windows_tasks.ps1`、`unregister_windows_tasks.ps1` | 02:00 / 02:05 |
| CodeArts 流水线 | `deploy/codearts/pipeline.yml` | 每日 02:00（时区以控制台为准，schema 未核实） |

### 6.2 产物路径

| 产物 | 路径 |
|---|---|
| 健康快照 | `artifacts/health/health-YYYYMMDD.json` |
| README 快照 | `artifacts/readme/readme-YYYYMMDD.json` |
| 日志 | `artifacts/logs/YYYYMMDD.log` |
| 失败标记 | `artifacts/logs/YYYYMMDD.failed` |

### 6.3 运行约束

- 外层超时 900 秒；`flock -n` 或 `IgnoreNew` 禁止并发
- 原子落盘：先写 `*.tmp`，成功后再重命名；失败删除临时文件并保留上次成功版本
- 失败退出码非 0；保留 30 天，先列后删
- 窗口计划任务的日期格式依赖区域设置（`%DATE%`），异常时改用 PowerShell 生成日期
- 未安装 cron、未注册计划任务、未触发流水线（本阶段）

---

## 7. 事实声明

- 本机无 `docker`、`nginx`、`hcloud`、`crontab`；**未执行 docker build、未执行 nginx -t、未执行 hcloud、未上云**。
- 部署与容器产物仅做静态校验，不代表已在目标机构建或部署。
- CodeArts 流水线 YAML **schema 未核实**，以控制台可视化配置为准；未托管代码时定时不生效。
- Node 版本口径：本机实测 **v24.19.0 / npm 11.17.0**，用户口径 v22.23.2 / 10.9.8；工程以 `engines.node >= 22.12` 为兼容目标。
- 看板巡检结论只读、不写仓库；历次巡检快照与修复 / 回滚事件由本地 SQLite 留存，历史页可回看快照明细、累计巡查次数与成功失败案例；写操作仅限桌面版 fixer 白名单范围。
- 示例数据中的路径均为相对路径，已脱敏；文档不含真实密钥、真实域名与个人绝对路径。
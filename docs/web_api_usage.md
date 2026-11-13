# RepoGuard Web API 使用说明

## 1. 安装与启动

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

默认只监听 `127.0.0.1:8000`，不要在生产环境使用 `--reload`。端口被占用时进程会直接启动失败，不会自动改端口。

访问地址：

| 用途 | 地址 |
|---|---|
| 单页控制台 | `http://127.0.0.1:8000/` |
| 健康检查 | `http://127.0.0.1:8000/api/health` |
| 检查接口 | `POST http://127.0.0.1:8000/api/review` |

原有规则引擎 CLI 调用方式完全不变：

```bash
cd backend
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo
```

未安装 FastAPI / uvicorn 时，规则引擎与 CLI 仍可独立运行，因为引擎本身零第三方依赖。

## 2. 仓库白名单配置 `REPOGUARD_ALLOWED_REPOS`

Web 层只能读取白名单内仓库目录。配置格式与规则：

- 主分隔符为系统路径分隔符：Windows 用 `;`，Linux/macOS 用 `:`。
- 同时接受 `|` 作为跨平台统一分隔符；字符串中出现 `|` 时优先按 `|` 拆分。
- 相对路径基准是 **RepoGuard 仓库根目录**，不是当前工作目录。
- 支持 `~` 展开；不存在、不是目录或不可读的项会被剔除。
- 主变量为 `REPOGUARD_ALLOWED_REPOS`，兼容旧变量 `REPOGUARD_ALLOWED_REPO_ROOTS`；两者同时存在时主变量优先。
- 未配置任何变量时，默认候选根为项目下 `demo-repo/`；该目录不存在时服务健康状态降级，不会放宽为任意路径。
- HTTP 请求体、请求头、查询参数都不能覆盖该配置。

### Windows `cmd`

```bat
cd backend
set REPOGUARD_ALLOWED_REPOS=C:\Users\student\RepoGuard\demo-repo;D:\课程\lab-repo
set REPOGUARD_DEFAULT_REPO=demo-repo
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

### Windows PowerShell

```powershell
cd backend
$env:REPOGUARD_ALLOWED_REPOS = "C:\Users\student\RepoGuard\demo-repo;D:\课程\lab-repo"
$env:REPOGUARD_DEFAULT_REPO = "demo-repo"
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

### Linux / macOS bash

```bash
cd backend
export REPOGUARD_ALLOWED_REPOS="/home/student/RepoGuard/demo-repo:/srv/lab-repo"
export REPOGUARD_DEFAULT_REPO="demo-repo"
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

### 跨平台统一分隔符示例

```bash
export REPOGUARD_ALLOWED_REPOS="/home/student/RepoGuard/demo-repo|/srv/lab-repo"
```

### 其余环境变量

| 环境变量 | 默认 | 范围 | 说明 |
|---|---:|---|---|
| `REPOGUARD_DEFAULT_REPO` | `demo-repo` | 允许根的相对标识 | 默认仓库标识 |
| `REPOGUARD_MAX_MANIFEST_CHARS` | `1000000` | 1～2,000,000 | 清单字符上限 |
| `REPOGUARD_MAX_MANIFEST_LINES` | `5000` | 1～20,000 | 清单行数上限 |
| `REPOGUARD_MAX_REQUEST_BYTES` | `2097152` | 65,536～16,777,216 | 请求体字节上限 |
| `REPOGUARD_REVIEW_TIMEOUT_SECONDS` | `30` | 1～120 | 单次检查超时 |
| `REPOGUARD_REVIEW_MAX_CONCURRENCY` | `2` | 1～8 | 并发检查上限 |
| `REPOGUARD_QUEUE_TIMEOUT_SECONDS` | `5` | 0～30 | 排队超时 |
| `REPOGUARD_CORS_ORIGINS` | 空 | 完整 origin，禁止 `*` | 跨域部署时配置 |
| `REPOGUARD_STATIC_DIR` | `backend/app/static` | 目录路径 | 静态目录覆盖 |
| `REPOGUARD_ALLOWED_REPO_ROOTS` | — | 同上 | 兼容旧变量，主变量优先 |

## 3. 接口示例与错误码

### 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

正常返回 HTTP 200：

```json
{
  "status": "ok",
  "service": "repoguard-web-api",
  "version": "1.0.0",
  "engine": "available",
  "default_repo": "demo-repo",
  "allowed_repo_root_count": 1,
  "time": "2026-01-01T00:00:00+00:00"
}
```

允许根为空或默认仓库缺失时返回 HTTP 503，`status` 为 `degraded`。健康检查不扫描仓库、不执行检查、不返回绝对路径。

### 检查接口

```bash
curl -X POST http://127.0.0.1:8000/api/review \
  -H "Content-Type: application/json" \
  -d '{"manifest":"A lab/uart.c\n","repo":"demo-repo"}'
```

Python 示例：

```python
import httpx

response = httpx.post(
    "http://127.0.0.1:8000/api/review",
    json={"manifest": "A lab/uart.c\n", "repo": "demo-repo"},
    timeout=35,
)
print(response.json())
```

成功响应直接复用规则引擎报告，六个顶层字段，不得外层包装：

```json
{
  "status": "正常",
  "summary": {
    "entry_count": 1,
    "issue_count": 2,
    "must_fix_count": 1,
    "suggestion_count": 1,
    "skipped_file_count": 0,
    "degraded_module_count": 0,
    "unparsed_line_count": 0
  },
  "files": [],
  "unparsed_lines": [],
  "degraded_modules": [],
  "warnings": []
}
```

### 错误码表

| HTTP | `error.code` | 触发条件 |
|---|---|---|
| 400 | `INVALID_JSON` | 请求体为空、截断、非 JSON 或顶层不是对象 |
| 400 | `INVALID_REPO_PATH` | `repo` 为空、超长、含控制字符、URL，或无默认仓库的相对路径 |
| 403 | `REPO_FORBIDDEN` | 含 `..`、盘符/UNC/设备路径、越界真实路径或符号链接逃逸 |
| 404 | `REPO_NOT_FOUND` | 白名单内但不存在或不是目录 |
| 404 | `NOT_FOUND` | 未知接口地址 |
| 405 | `METHOD_NOT_ALLOWED` | 接口不支持当前请求方法 |
| 413 | `MANIFEST_TOO_LARGE` | 清单字符数、字节数或行数超限 |
| 413 | `REQUEST_TOO_LARGE` | 请求体超过上限 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 请求内容类型不是 `application/json` |
| 422 | `VALIDATION_ERROR` | 字段缺失、类型错误或请求体结构不合法 |
| 429 | `REVIEW_BUSY` | 并发已满且排队超时 |
| 500 | `INTERNAL_ERROR` | 引擎未预期异常或报告序列化失败 |
| 503 | `ENGINE_UNAVAILABLE` | 引擎不可导入、允许根为空，无法执行检查 |
| 503 | `STATIC_NOT_FOUND` | `index.html` 缺失 |
| 504 | `REVIEW_TIMEOUT` | 检查超过 `REPOGUARD_REVIEW_TIMEOUT_SECONDS` |

所有响应带 `X-Request-ID`；API 响应带 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`；页面响应额外带 `X-Frame-Options: DENY` 与 CSP。

## 4. 人工验收与故障排查

人工验收步骤：

1. 启动服务，浏览器打开 `http://127.0.0.1:8000/`，确认页面显示服务正常。
2. 粘贴一份包含新增、修改、删除状态的变更清单。
3. 点击「开始检查」，确认按钮进入加载态。
4. 确认结果顶部展示七项统计。
5. 确认「必须修改」分组先于「优化建议」显示。
6. 确认单条问题包含行号、描述、建议与规则编号。
7. 提交空清单，确认提示「请先粘贴变更清单」且不发请求。
8. 填写越界仓库路径，确认显示中文错误提示并保留输入。
9. 确认 360 px 宽度下无横向滚动。

记录栏：浏览器版本 ______ / 操作系统 ______ / 结果 ______

常见故障：

| 现象 | 原因 | 处理 |
|---|---|---|
| 健康检查 503 `degraded` | 允许根为空或默认仓库被删除 | 检查 `REPOGUARD_ALLOWED_REPOS` 与默认仓库目录 |
| 检查接口 503 `ENGINE_UNAVAILABLE` | 未配置可用仓库目录或引擎不可导入 | 配置允许根，确认后端目录完整 |
| 页面 503 `STATIC_NOT_FOUND` | `index.html` 缺失 | 检查 `backend/app/static/index.html` |
| 启动失败提示端口占用 | 8000 端口被其他程序占用 | 关闭占用程序或显式换端口启动 |
| 未安装 Web 依赖 | 未执行 `pip install -r requirements.txt` | 安装依赖；引擎与 CLI 仍可独立使用 |
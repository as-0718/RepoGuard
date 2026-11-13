# RepoGuard Webhook 与 OpenAPI 回写使用说明

## 1. 功能概述与整体架构

RepoGuard 阶段 4 增加两项能力：

1. **Webhook 自动触发**：接收代码平台 PR/MR 创建、更新事件，校验签名后自动触发仓库检查。
2. **OpenAPI 回写 PR 评论**：把检查结果渲染为评论，通过可配置的 OpenAPI 适配层写回 PR/MR。

整体链路：

```text
代码平台
  → POST /webhook
  → HMAC-SHA256 验签 + 时间戳/重放窗口
  → 解析与归一化事件
  → 仓库白名单映射
  → 幂等占位
  → 有界队列 / worker
  → engine.run_check() 一次
  → 评论渲染
  → OpenAPI 适配层回写
  → DeliveryRecord
```

生产约束：

- Webhook 是**独立进程**，默认监听 `127.0.0.1:8010`，不注册到阶段 2 的 FastAPI 应用。
- 检查逻辑 100% 复用 `backend/app/core/rules/engine.py::run_check()`，每个事件只调用一次。
- 不远程 clone 仓库；事件中的仓库标识只能映射到 `REPOGUARD_ALLOWED_REPOS` 白名单。
- 默认出站模式 `disabled`，即零出站；只有显式配置 `mock` 或 `live` 才会尝试回写。
- 不新增第三方依赖；Web 服务与 HTTP 客户端依赖的固定版本见 `backend/requirements.txt`。

### 包结构

```text
backend/app/webhook/
├── __init__.py       包导出
├── __main__.py       独立进程入口
├── app.py            FastAPI 应用工厂与 lifespan
├── routes.py         POST /webhook、GET /healthz、错误映射
├── service.py        唯一编排：验签→解析→幂等→检查→渲染→回写→记录
├── queue.py          有界队列、worker、并发闸门
├── idempotency.py    单实例内存幂等
├── parser.py         事件解析、归一化、路径清洗、清单构造
├── signature.py      HMAC-SHA256、时间戳、重放窗口、密钥轮换
├── security.py       仓库映射、日志/评论脱敏
├── render.py         评论渲染、分级排序、截断、二次脱敏
├── settings.py       环境变量加载与校验
└── models.py         事件、任务、评论、投递记录等数据模型

backend/app/integrations/
├── __init__.py       轻量导出（不预加载 HTTP 客户端）
├── models.py         OpenApiProfile、PublishResult、配置校验
├── client.py         HttpClient Protocol + httpx 实现
├── openapi.py        ConfigurableOpenApiAdapter、重试与 SSRF 防护
└── mock.py           MockOpenApiAdapter、进程内 MockOpenApiService
```

## 2. 快速开始

### 2.1 环境要求

- Python 3.10+
- 已安装 `backend/requirements.txt` 中的固定版本依赖
- 运行环境可访问被检查仓库的本地路径
- 生产环境需要一个足够长的随机签名密钥

本阶段没有新增依赖。`httpx` 目前位于 `requirements.txt` 的测试依赖段，但运行时也会复用同一固定版本；部署时必须安装完整 `requirements.txt`。

```bash
cd backend
python -m pip install -r requirements.txt
```

### 2.2 最小启动

Windows `cmd`：

```bat
cd backend
set REPOGUARD_WEBHOOK_SECRET=replace-with-a-long-random-secret
set REPOGUARD_OPENAPI_MODE=disabled
python -m app.webhook
```

Linux/macOS：

```bash
cd backend
export REPOGUARD_WEBHOOK_SECRET="replace-with-a-long-random-secret"
export REPOGUARD_OPENAPI_MODE="disabled"
python -m app.webhook
```

默认监听 `127.0.0.1:8010`，接收路径 `/webhook`，健康检查 `/healthz`：

```bash
curl http://127.0.0.1:8010/healthz
```

### 2.3 停止

前台运行时按 `Ctrl+C`。服务会在 `REPOGUARD_WEBHOOK_STOP_TIMEOUT_SECONDS`（默认 10 秒）内尝试停止 worker，并等待已入队任务尽可能完成。

## 3. 入站签名机制

### 3.1 签名算法

固定算法：**HMAC-SHA256**。

签名串：

```text
timestamp + "." + raw_body
```

其中：

- `timestamp` 是时间戳请求头的原始值（去除首尾空白）
- `raw_body` 是实际发送的原始字节，不是重新序列化后的 JSON
- 输出为 64 位小写十六进制
- 支持 `sha256=<hex>` 前缀；前缀可通过环境变量置空以接受裸十六进制

### 3.2 默认请求头

| 请求头 | 默认值 | 作用 |
|---|---|---|
| `X-RepoGuard-Signature` | `sha256=<hex>` | HMAC 签名 |
| `X-RepoGuard-Timestamp` | 10 位秒或 13 位毫秒 | 时间戳与重放校验 |
| `X-RepoGuard-Event` | `pr.created` 等 | 事件类型 |
| `X-RepoGuard-Delivery` | 平台投递 ID | 事件 ID 回退 |

头名均可在环境变量中覆盖。

### 3.3 时间戳与重放窗口

- 10 位纯数字按秒解析
- 13 位纯数字按毫秒解析
- 默认重放窗口 300 秒，可配置 30～900 秒
- 服务端时间与时间戳差值绝对值不得超过窗口
- 时间戳超前超窗返回 `WEBHOOK_TIMESTAMP_INVALID`，落后超窗返回 `WEBHOOK_TIMESTAMP_EXPIRED`

### 3.4 密钥轮换

支持当前密钥 + 上一版本密钥：

1. 平台配置新密钥，同时保留旧密钥一段时间
2. RepoGuard 设置：
   - `REPOGUARD_WEBHOOK_SECRET=<新密钥>`
   - `REPOGUARD_WEBHOOK_SECRET_PREVIOUS=<旧密钥>`
3. 重启服务
4. 观察旧密钥请求比例，降为 0 后清空 `REPOGUARD_WEBHOOK_SECRET_PREVIOUS`
5. 再重启一次

验签先使用当前密钥，失败后再用上一版本密钥；两者都不匹配时统一返回 `WEBHOOK_SIGNATURE_INVALID`，不区分密钥版本。

### 3.5 可运行签名示例

```python
import hashlib
import hmac
import json
import time
import urllib.request

secret = "replace-with-your-test-secret"
payload = {
    "event_id": "evt-demo-001",
    "action": "opened",
    "repository": {"full_name": "demo-repo"},
    "pull_request": {
        "number": 12,
        "base": {"sha": "a" * 40},
        "head": {"sha": "b" * 40},
    },
    "changed_files": ["lab/uart/uart_demo.c"],
}

raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
timestamp = str(int(time.time()))
signature = hmac.new(
    secret.encode("utf-8"),
    timestamp.encode("utf-8") + b"." + raw_body,
    hashlib.sha256,
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-RepoGuard-Signature": "sha256=" + signature,
    "X-RepoGuard-Timestamp": timestamp,
    "X-RepoGuard-Event": "pr.created",
    "X-RepoGuard-Delivery": "demo-delivery-001",
}

request = urllib.request.Request(
    "http://127.0.0.1:8010/webhook",
    data=raw_body,
    headers=headers,
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.status, response.read().decode("utf-8"))
```

注意：签名必须基于**实际发送的字节**。先计算签名再重新序列化 JSON 会改变字节内容，导致 401。

## 4. 完整环境变量清单

### 4.1 入站与接收端

| 环境变量 | 默认值 | 取值范围/必填 | 说明 |
|---|---|---|---|
| `REPOGUARD_WEBHOOK_ENABLED` | `true` | 布尔 | 总开关；false 时 `/webhook` 返回 503 |
| `REPOGUARD_WEBHOOK_HOST` | `127.0.0.1` | IPv4/IPv6/主机名 | 监听地址，禁止默认 0.0.0.0 |
| `REPOGUARD_WEBHOOK_PORT` | `8010` | 1～65535 | 监听端口 |
| `REPOGUARD_WEBHOOK_PATH` | `/webhook` | `/` 开头、1～64 | 接收路径 |
| `REPOGUARD_WEBHOOK_SECRET` | 空 | 生产必填 | 当前 HMAC 签名密钥 |
| `REPOGUARD_WEBHOOK_SECRET_PREVIOUS` | 空 | 可选 | 上一版本密钥，用于轮换 |
| `REPOGUARD_WEBHOOK_SIGNATURE_HEADER` | `X-RepoGuard-Signature` | HTTP 头名 | 签名头 |
| `REPOGUARD_WEBHOOK_SIGNATURE_PREFIX` | `sha256=` | 可为空 | 签名前缀 |
| `REPOGUARD_WEBHOOK_TIMESTAMP_HEADER` | `X-RepoGuard-Timestamp` | HTTP 头名 | 时间戳头 |
| `REPOGUARD_WEBHOOK_EVENT_HEADER` | `X-RepoGuard-Event` | HTTP 头名 | 事件类型头 |
| `REPOGUARD_WEBHOOK_DELIVERY_HEADER` | `X-RepoGuard-Delivery` | HTTP 头名 | 投递标识头 |
| `REPOGUARD_WEBHOOK_EVENT_TYPES` | `pr.created,pr.updated,mr.created,mr.updated` | 逗号或 `|` 分隔 | 事件白名单，大小写不敏感 |
| `REPOGUARD_WEBHOOK_FIELD_MAP` | 空 JSON 对象 | JSON 对象 | 覆盖默认字段路径，值为字符串数组 |
| `REPOGUARD_WEBHOOK_EVENT_KIND_MAP` | 空 JSON 对象 | JSON 对象 | 自定义事件类型 → `created`/`updated` |
| `REPOGUARD_WEBHOOK_REPO_MAP` | 空 JSON 对象 | JSON 对象 | 事件仓库标识 → 白名单标识 |
| `REPOGUARD_WEBHOOK_REPLAY_WINDOW_SECONDS` | `300` | 30～900 | 重放窗口 |
| `REPOGUARD_WEBHOOK_MAX_BODY_BYTES` | `1048576` | 65,536～8,388,608 | 请求体上限 |
| `REPOGUARD_WEBHOOK_MAX_CHANGED_FILES` | `5000` | 1～20,000 | 单事件变更文件上限 |
| `REPOGUARD_ALLOWED_REPOS` | 阶段 2 默认 | 阶段 2 格式 | 只读复用仓库白名单 |
| `REPOGUARD_DEFAULT_REPO` | 阶段 2 默认 | 阶段 2 格式 | 只读复用默认仓库 |

### 4.2 队列、幂等与评论

| 环境变量 | 默认值 | 取值范围 | 说明 |
|---|---|---|---|
| `REPOGUARD_WEBHOOK_IDEMPOTENCY_TTL_SECONDS` | `86400` | 60～604,800 | 幂等记录 TTL |
| `REPOGUARD_WEBHOOK_IDEMPOTENCY_CAPACITY` | `10000` | 100～100,000 | 幂等记录容量 |
| `REPOGUARD_WEBHOOK_IDEMPOTENCY_RETRY_FAILED` | `false` | 布尔 | 是否允许失败事件重放 |
| `REPOGUARD_WEBHOOK_QUEUE_CAPACITY` | `100` | 1～1,000 | 队列容量 |
| `REPOGUARD_WEBHOOK_WORKER_CONCURRENCY` | `2` | 1～8 | worker 数与并发上限 |
| `REPOGUARD_WEBHOOK_TASK_TIMEOUT_SECONDS` | `120` | 30～300 | 单任务执行预算 |
| `REPOGUARD_WEBHOOK_STOP_TIMEOUT_SECONDS` | `10` | 1～60 | 优雅停机预算 |
| `REPOGUARD_WEBHOOK_SYNC_MODE` | `false` | 布尔 | true 时同步执行并等待结果 |
| `REPOGUARD_WEBHOOK_NOTIFY_ON_FAILURE` | `true` | 布尔 | 失败/降级是否回写说明 |
| `REPOGUARD_WEBHOOK_NOTIFY_ON_CLEAN` | `true` | 布尔 | 无问题是否回写“未发现问题” |
| `REPOGUARD_WEBHOOK_MAX_COMMENT_CHARS` | `60000` | 1,000～100,000 | 评论长度上限 |
| `REPOGUARD_WEBHOOK_RECORD_BUFFER_SIZE` | `500` | 10～10,000 | 内存投递记录容量 |
| `REPOGUARD_WEBHOOK_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR | 日志级别 |
| `REPOGUARD_WEBHOOK_DUPLICATE_COMMENT_CHECK` | `false` | 布尔 | 预留的重复评论检测开关 |

### 4.3 出站 OpenAPI

| 环境变量 | 默认值 | 必填性/范围 | 说明 |
|---|---|---|---|
| `REPOGUARD_OPENAPI_MODE` | `disabled` | `disabled`/`mock`/`live` | 出站模式 |
| `REPOGUARD_OPENAPI_BASE_URL` | 空 | live 必填；仅 HTTPS（loopback 例外） | OpenAPI 基地址 |
| `REPOGUARD_OPENAPI_COMMENT_ENDPOINT_TEMPLATE` | 空 | live 必填；含 `{repo}`/`{pr_number}` | 评论 endpoint 模板 |
| `REPOGUARD_OPENAPI_CHANGED_FILES_ENDPOINT_TEMPLATE` | 空 | 可选；含 `{repo}`/`{base_sha}`/`{head_sha}` | 获取变更清单 endpoint |
| `REPOGUARD_OPENAPI_BODY_TEMPLATE` | 空 | live 必填；含 `{markdown}` | 评论请求体模板 |
| `REPOGUARD_OPENAPI_AUTH_SCHEME` | `bearer` | `bearer`/`header`/`none` | 认证方式 |
| `REPOGUARD_OPENAPI_AUTH_HEADER` | `Authorization` | HTTP 头名 | 认证头名 |
| `REPOGUARD_OPENAPI_AUTH_PREFIX` | `Bearer ` | 字符串 | 认证前缀 |
| `REPOGUARD_OPENAPI_TOKEN_ENV` | `REPOGUARD_OPENAPI_TOKEN` | 非空 | 保存令牌的环境变量名 |
| `REPOGUARD_OPENAPI_TOKEN` | 空 | live 且非 none 认证时必填 | OpenAPI 令牌，只从环境变量读取 |
| `REPOGUARD_OPENAPI_ALLOWED_HOSTS` | 空 | live 必填；逗号分隔；禁止 `*` | 出站主机白名单 |
| `REPOGUARD_OPENAPI_TIMEOUT_SECONDS` | `10` | 1～60 | 单次请求超时 |
| `REPOGUARD_OPENAPI_MAX_RETRIES` | `2` | 0～5 | 最大重试次数（总尝试 = 1 + 重试） |
| `REPOGUARD_OPENAPI_BACKOFF_BASE_SECONDS` | `0.5` | 0.1～5 | 退避基数（指数退避 + 抖动） |
| `REPOGUARD_OPENAPI_SUCCESS_STATUS_CODES` | `200,201` | 逗号分隔整数 | 视为成功的平台状态码 |
| `REPOGUARD_OPENAPI_VERIFY_TLS` | `true` | 布尔 | 仅 loopback 允许 false |
| `REPOGUARD_OPENAPI_FOLLOW_REDIRECTS` | `false` | 固定 false | 不允许跟随重定向 |
| `REPOGUARD_OPENAPI_USER_AGENT` | `RepoGuard-Webhook/1.0` | 字符串 | 出站 User-Agent |
| `REPOGUARD_OPENAPI_COMMENT_MARKER_TEMPLATE` | `<!-- repoguard:event:{event_id} -->` | 含 `{event_id}` | 评论来源标记 |
| `REPOGUARD_OPENAPI_CHANGED_FILES_RESPONSE_PATH` | `data.changed_files` | 点分路径 | 变更清单响应字段 |
| `REPOGUARD_OPENAPI_COMMENT_ID_RESPONSE_PATH` | `data.id` | 点分路径 | 评论 ID 响应字段 |

### 4.4 测试专用

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `REPOGUARD_WEBHOOK_E2E_LOOPBACK` | 未设置 | 仅值为 `1` 时运行可选回环 E2E，仅绑定 `127.0.0.1:0` |

## 5. 三种出站模式

| 模式 | 语义 | 是否出站 | 适用场景 |
|---|---|---|---|
| `disabled`（默认） | 检查照常执行，但不构造出站适配器，不回写评论 | 否，零出站 | 首次部署、安全演练、只想本地检查 |
| `mock` | 使用进程内 `MockOpenApiAdapter`，记录评论与请求 | 否，只在内存 | 本地演示、离线自测 |
| `live` | 使用 `ConfigurableOpenApiAdapter` 调用真实 OpenAPI | 是，仅允许 HTTPS 与白名单主机 | 真实对接生产平台 |

切换：

```bat
set REPOGUARD_OPENAPI_MODE=mock
REM 或
set REPOGUARD_OPENAPI_MODE=disabled
REM 或
set REPOGUARD_OPENAPI_MODE=live
```

`disabled` 下即使配置了令牌也不会读取或发送。

`live` 模式缺配置时 **fail-closed**：

- 不静默回退到 `mock` 或 `disabled`
- `/healthz` 返回 503 `degraded`
- `/webhook` 返回 503 `OPENAPI_NOT_CONFIGURED`
- 错误详情包含缺失字段名（不含字段值、不含令牌）

## 6. 错误码与排查建议

### 6.1 入站响应

| HTTP | 错误码 | 触发条件 | 排查建议 |
|---|---|---|---|
| 200 | — | 同步模式下检查与回写成功 | 无需处理 |
| 202 | — | 异步接收、重复事件、忽略事件、降级 | 正常接收；查看 `action` 与 `status` |
| 400 | `WEBHOOK_INVALID_JSON` | 验签后请求体为空、截断、非 UTF-8、非 JSON 对象 | 检查平台发送的原始 body 与编码 |
| 401 | `WEBHOOK_SIGNATURE_MISSING` | 缺少签名头 | 检查 `REPOGUARD_WEBHOOK_SIGNATURE_HEADER` 与平台配置 |
| 401 | `WEBHOOK_SIGNATURE_INVALID` | 签名不匹配、格式错误、长度错误 | 确认签名基于原始字节、算法与密钥一致 |
| 401 | `WEBHOOK_TIMESTAMP_MISSING` | 缺少时间戳头 | 检查时间戳头名 |
| 401 | `WEBHOOK_TIMESTAMP_INVALID` | 非 10/13 位数字、超前超窗 | 检查平台时钟与时间戳单位 |
| 401 | `WEBHOOK_TIMESTAMP_EXPIRED` | 落后超过重放窗口 | 检查平台时钟；必要时调整窗口 |
| 403 | `WEBHOOK_REPO_FORBIDDEN` | 仓库标识未映射到白名单 | 检查 `REPOGUARD_ALLOWED_REPOS`、`REPOGUARD_WEBHOOK_REPO_MAP` |
| 404 | `NOT_FOUND` | 访问不存在的路径 | 检查 `REPOGUARD_WEBHOOK_PATH` |
| 405 | `METHOD_NOT_ALLOWED` | 方法不符合路由 | `/webhook` 只接受 POST，`/healthz` 只接受 GET |
| 409 | `WEBHOOK_EVENT_CONFLICT` | 同一事件 ID 携带不同内容 | 检查平台事件 ID 生成逻辑 |
| 413 | `WEBHOOK_PAYLOAD_TOO_LARGE` | 请求体超过上限 | 调整 `REPOGUARD_WEBHOOK_MAX_BODY_BYTES` 或减少 payload |
| 415 | `WEBHOOK_UNSUPPORTED_MEDIA_TYPE` | Content-Type 非 JSON | 平台必须发送 `application/json` |
| 422 | `WEBHOOK_EVENT_INVALID` | 事件类型无法识别、必填字段缺失/类型错误 | 检查事件头与字段映射 |
| 429 | `WEBHOOK_BUSY` | 队列已满 | 降低事件频率或提高队列容量/并发 |
| 500 | `WEBHOOK_INTERNAL_ERROR` | 未预期异常 | 查看服务日志中的 `request_id` |
| 502 | — | 同步模式下检查完成但回写失败；响应 `status=failed` | 查看投递记录中的 `OPENAPI_*` 错误码与 OpenAPI 配置 |
| 503 | `WEBHOOK_DISABLED` | `REPOGUARD_WEBHOOK_ENABLED=false` | 确认总开关 |
| 503 | `WEBHOOK_SECRET_NOT_CONFIGURED` | 签名密钥未配置 | 配置 `REPOGUARD_WEBHOOK_SECRET` |
| 503 | `OPENAPI_NOT_CONFIGURED` | live 模式缺少配置 | 检查 base URL、endpoint、模板、主机白名单、令牌 |
| 504 | — | 同步检查超过预算；响应 `status=timeout` | 缩小变更范围或提高任务预算；投递记录错误码为 `WEBHOOK_TIMEOUT` |

规则引擎不可导入时，`/healthz` 会显示 `engine=unavailable` 并整体降级；异步事件会在后台记录失败，同步请求返回 502，不会伪装成成功。

### 6.2 出站结果错误码（记录/日志/同步 502 详情）

| 错误码 | 含义 | 是否重试 |
|---|---|---|
| `OPENAPI_AUTH_FAILED` | 平台返回 401/403 | 否 |
| `OPENAPI_NOT_FOUND` | 平台返回 404 | 否 |
| `OPENAPI_REDIRECT_FORBIDDEN` | 平台返回 3xx | 否 |
| `OPENAPI_COMMENT_TOO_LONG` | 平台返回 400/413 | 否 |
| `OPENAPI_UNAVAILABLE` | 连接失败、5xx、429 重试耗尽 | 已重试 |
| `OPENAPI_TIMEOUT` | 超时或预算耗尽 | 已重试 |
| `OPENAPI_HOST_FORBIDDEN` | 主机不在白名单或非 HTTPS/非 loopback | 不发请求 |
| `OPENAPI_NOT_CONFIGURED` | 配置缺失 | 不发请求 |

异步模式下，202 已返回后的后台失败不会改变 HTTP 响应；必须通过日志、`/healthz` 的 `recent_delivery_failures` 与服务端投递记录观测。

## 7. 离线演示与自测

### 7.1 用 mock 模式跑通完整链路

使用一次性假密钥，不接真实平台：

```bat
cd backend
set REPOGUARD_WEBHOOK_SECRET=test-only-secret-not-real
set REPOGUARD_OPENAPI_MODE=mock
set REPOGUARD_WEBHOOK_SYNC_MODE=true
set REPOGUARD_ALLOWED_REPOS=C:\path\to\demo-repo
python -m app.webhook
```

然后用第 3.5 节的签名示例向 `http://127.0.0.1:8010/webhook` 发送事件。`mock` 模式只在内存记录评论，不访问外部网络。

### 7.2 纯离线 ASGI 自测

测试基础设施提供了 `backend/tests/webhook_helpers.py` 与 `WebhookASGIClient`，使用 `httpx.ASGITransport` 在进程内调用应用，不启动真实端口：

```bash
cd backend
python -m unittest discover -s tests -p "test_webhook_*.py" -v
```

预期：

- 新增测试文件 67 条方法
- 66 passed + 1 条可选回环 skipped
- 不使用 Web 框架内置同步测试客户端
- 不引入其他测试运行器
- 不访问真实网络或真实端口

### 7.3 确认零网络 / 零真实端口

1. 不设置 `REPOGUARD_WEBHOOK_E2E_LOOPBACK=1`；可选回环用例会跳过。
2. 运行上述新增测试，所有 API 调用均走 `httpx.ASGITransport`，出站均走 `httpx.MockTransport` 或内存 Mock。
3. 测试代码对 `socket.socket` 与 `socket.create_connection` 做了断言补丁，真实 socket 调用会失败。
4. `disabled` 模式不构造出站适配器；`mock` 模式不创建 socket。
5. 只有显式设置 `REPOGUARD_WEBHOOK_E2E_LOOPBACK=1` 时，才允许在 `127.0.0.1:0` 启动一个临时回环服务，且该用例不属于默认门禁。

## 8. 安全注意事项

1. **密钥只走环境变量**：`REPOGUARD_WEBHOOK_SECRET`、`REPOGUARD_WEBHOOK_SECRET_PREVIOUS`、`REPOGUARD_OPENAPI_TOKEN` 不得写入仓库、配置文件、镜像或命令行历史。
2. **日志脱敏**：日志只记录 `configured/unset`、`present/absent`，不打印密钥、令牌、原始请求体、清单正文、评论正文或绝对路径。
3. **常量时间比较**：验签只使用 `hmac.compare_digest`。
4. **重放防护**：默认 300 秒窗口；不要将窗口扩大到无实际意义。
5. **主机白名单与 SSRF 防护**：`live` 仅允许配置的精确主机，禁止 `*`、后缀通配、私网/链路本地/元数据地址；默认不跟随重定向。
6. **TLS**：默认 `verify_tls=true`；`false` 只允许 loopback，不得用于生产。
7. **白名单仓库**：事件仓标识只能映射到 `REPOGUARD_ALLOWED_REPOS`，不远程 clone，不读取任意系统路径。
8. **单实例内存幂等**：本阶段只做单进程内存去重；重启或多实例部署可能重复回评。需要跨实例幂等时，应另立阶段引入共享存储，不能声称当前已支持。
9. **失败不伪装成功**：出站失败记录 `failed`，不记录为 `delivered`；同步模式返回 502，异步模式通过记录和健康指标暴露。

## 9. 假设清单与待确认项

以下结论无法在本环境核实官方文档，全部按“可配置默认值 + 适配层”处理，不是硬编码契约。

| 编号 | 假设 | 默认 | 可配置 |
|---|---|---|---|
| A01 | 签名头名 | `X-RepoGuard-Signature` | `REPOGUARD_WEBHOOK_SIGNATURE_HEADER` |
| A02 | 签名值格式 | `sha256=<64 位 hex>` | `REPOGUARD_WEBHOOK_SIGNATURE_PREFIX` |
| A03 | 签名串 | `timestamp + "." + raw_body` | 不支持配置，变更需改规格 |
| A04 | 签名算法 | HMAC-SHA256 | 仅 `sha256` |
| A05 | 时间戳头名 | `X-RepoGuard-Timestamp` | 可配置 |
| A06 | 时间戳单位 | 10 位秒 / 13 位毫秒 | 自动识别 |
| A07 | 事件类型头名 | `X-RepoGuard-Event` | 可配置 |
| A08 | 事件类型取值 | `pr.created`、`pr.updated`、`mr.created`、`mr.updated` | `REPOGUARD_WEBHOOK_EVENT_TYPES` |
| A09 | 投递标识头名 | `X-RepoGuard-Delivery` | 可配置 |
| A10 | 事件标识字段 | `event_id` → `id` → `delivery_id` | `REPOGUARD_WEBHOOK_FIELD_MAP` |
| A11 | 仓库标识字段 | `repository.full_name` → `repository.name` → `repo` → `project.path_with_namespace` | `field_map` |
| A12 | PR 编号字段 | `pull_request.number` → `merge_request.iid` → `number` | `field_map` |
| A13 | 变更文件字段 | `changed_files` → `added_files`/`modified_files`/`removed_files` | `field_map` |
| A14 | 基线/头提交字段 | `pull_request.base.sha` / `pull_request.head.sha`；MR 对应目标/最后提交 | `field_map` |
| A15 | 评论 endpoint | 无默认值，`live` 必填 | `REPOGUARD_OPENAPI_COMMENT_ENDPOINT_TEMPLATE` |
| A16 | 变更清单 endpoint | 无默认值，未配置表示不支持 | `REPOGUARD_OPENAPI_CHANGED_FILES_ENDPOINT_TEMPLATE` |
| A17 | 认证方式 | `bearer` + `Authorization: Bearer <token>` | `AUTH_SCHEME`/`AUTH_HEADER`/`AUTH_PREFIX`/`TOKEN_ENV` |
| A18 | 评论请求体模板 | 无默认值，`live` 必填 | `REPOGUARD_OPENAPI_BODY_TEMPLATE` |
| A19 | 评论 ID 响应路径 | `data.id` | `REPOGUARD_OPENAPI_COMMENT_ID_RESPONSE_PATH` |
| A20 | 变更清单响应路径 | `data.changed_files` | `REPOGUARD_OPENAPI_CHANGED_FILES_RESPONSE_PATH` |
| A21 | 评论长度上限 | 60,000 字符 | `REPOGUARD_WEBHOOK_MAX_COMMENT_CHARS` |
| A22 | 成功状态码 | `200,201` | `REPOGUARD_OPENAPI_SUCCESS_STATUS_CODES` |
| A23 | 限流状态码 | 429 | 固定，与 5xx 一同重试 |

### 9.1 拿到真实官方文档后怎么改

不需要改架构：

1. 把真实的签名头名、事件头名、认证头名写入对应环境变量。
2. 把真实评论 endpoint、变更清单 endpoint、请求体模板接入 `REPOGUARD_OPENAPI_*_TEMPLATE`。
3. 把真实响应字段路径接入 `REPOGUARD_OPENAPI_*_RESPONSE_PATH`。
4. 把真实主机加入 `REPOGUARD_OPENAPI_ALLOWED_HOSTS`。
5. 如需调整评论长度上限或成功状态码，修改对应环境变量。
6. 仅当签名串或算法与当前不同（A03/A04），才需要改适配层/规格。

### 9.2 待确认项

1. `httpx` 当前位于 `requirements.txt` 测试依赖段，运行时复用同一固定版本。本阶段不改 `requirements.txt`、不改 `test_requirements_txt`；真实部署阶段再统一整理依赖段。
2. 当前 Windows 沙箱无法创建符号链接，2 条既有符号链接相关测试表现为平台异常。该问题非阶段 4 引入，按既定决策只记录、不修复旧测试。
3. 单实例内存幂等不支持多实例；若未来需要横向扩容，必须引入共享幂等存储并单独评审。
4. 失败/降级默认回写说明、无问题默认回写“未发现问题”；如平台不希望收到此类评论，可通过 `REPOGUARD_WEBHOOK_NOTIFY_ON_FAILURE` / `REPOGUARD_WEBHOOK_NOTIFY_ON_CLEAN` 关闭。`disabled` 模式始终零出站。
5. 真实平台限流策略、签名串、事件字段名称等仍待官方资料确认；确认前只使用配置，不修改架构。
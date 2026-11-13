# RepoGuard Webhook 自动触发与 CodeArts OpenAPI 回写 —— 编码任务清单

> feature：`webhook_openapi`（阶段 4）
> 文档路径：`.codeartsdoer/specs/webhook_openapi/tasks.md`
> 唯一依据：`.codeartsdoer/specs/webhook_openapi/spec.md`（已确认）、`.codeartsdoer/specs/webhook_openapi/design.md`（已确认，含 2.2 接口、2.3 数据模型、2.4 逐文件签名、2.5 技术方案、2.5.8 环境变量）
> 存量基线：`backend/app/core/rules/**`、`backend/app/api/**`、`backend/app/health/**`、`backend/app/readme/**`、`backend/app/shared/**`、`backend/requirements.txt`、`backend/tests/**`（310 条）
> 本文档只描述「做什么、做到什么程度、如何验收」，**不包含任何实现代码**；实现阶段不得修改 `spec.md` 与 `design.md`，不得修改任何既有文件。

---

## 1. 执行约定（所有任务共用）

### 1.1 用户已确认的 7 项决策（硬约束，不得在实现中偏离）

- [ ] **D1 可配置适配层**：CodeArts 官方文档在本环境不可核实，全部平台细节按「可配置适配层 + 假设清单（spec 7.6 / design 2.5.8）」推进；未来只允许改配置与适配层，不得改架构、不得把假设写成不可覆盖的常量。
- [ ] **D2 独立进程**：Webhook 是独立进程，默认 `127.0.0.1:8010`，**不挂到阶段 2 应用**，阶段 2 路由集合不变。
- [ ] **D3 默认零出站**：`openapi_mode` 默认 `disabled`，零出站；`mock` 仅用于演示与测试（进程内/内存）；`live` 才真实对接，且必须显式配置。
- [ ] **D4 单实例幂等**：接受单进程内存幂等局限，**不引入 Redis、数据库、消息队列等外部依赖**；重启与多实例可能重复回评，必须在文档中明确标注；评论来源标记必须保留。
- [ ] **D5 依赖不变**：`httpx` 继续留在 `requirements.txt` 测试依赖段并在运行时复用；**本阶段不修改 `requirements.txt`、不修改 `tests/test_engine.py::test_requirements_txt`**；依赖整理留到部署阶段。
- [ ] **D6 既有平台异常**：不修复 2 条既有 Windows 符号链接测试波动；那是平台波动、非本阶段引入，**禁止修改这 2 条测试**；阶段 4 只记录为既有平台异常，不纳入新增失败。
- [ ] **D7 失败回写口径**：失败/降级默认回写失败说明，无问题默认回写「未发现问题」；`disabled` 模式仍为零出站。

### 1.2 全局红线（任何任务不得突破）

| 编号 | 红线 | 机械判定方式 |
|------|------|-------------|
| R-01 | 18 个新增产品文件只落在 `backend/app/webhook/**`（13）与 `backend/app/integrations/**`（5） | 新增文件清单与第 2 节目录树逐项比对 |
| R-02 | 不修改 13 个冻结文件、`backend/app/api/**`、`backend/app/static/index.html`、阶段 3 三个包 | 改动前后 SHA-256 比对，差异 0 |
| R-03 | 不修改 `backend/requirements.txt` | 哈希固定为 `18a816cd88636be844e7cd3a6662b2cdc2e13324420031f082a331a520b4bbcf`（7 行三段式） |
| R-04 | 不修改 `backend/tests/` 下既有 17 个 `test_*.py`、`tests/__init__.py`、`tests/fixtures/sample_changes.txt` | 文件哈希与 mtime 不变 |
| R-05 | 310 条基线不减少；不得新增 failed / error（既有 2 条符号链接异常除外，只记录） | `python -m unittest discover -s tests -v` 结果比对 |
| R-06 | `python -m unittest tests.test_cli -v` 必须 12 passed；CLI 参数、退出码、输出格式不变 | 用例计数 + JSON 键集合 |
| R-07 | 阶段 2 `test_api` 全过；路由集合不含 `/webhook`、`/healthz` | 路由集合断言 |
| R-08 | 新增包导入方向通过既有 `test_engine.py::test_import_direction` | AST 审计 + 该用例通过 |
| R-09 | 产品代码除日志与 `live` 出站外不写文件、不执行被检查代码、不远程 clone | AST/文本审计 |
| R-10 | 默认 `disabled` 零出站；任何测试不得访问公网、不得监听真实端口 | socket 补丁 + 端口占用对比 |
| R-11 | 不新增第三方依赖（复用 `fastapi==0.115.6`、`uvicorn==0.34.0`、`httpx==0.28.1`） | 依赖导入审计 + `requirements.txt` 哈希 |
| R-12 | 测试统一 `unittest` 风格，运行器为 `python -m unittest`；不得引入其他测试运行器或其断言/夹具风格 | 测试文件静态扫描 |
| R-13 | 新增测试的出站通道只允许：`httpx.MockTransport`、进程内 `MockOpenApiAdapter`、进程内 `MockOpenApiService`（`httpx.ASGITransport`） | 测试静态扫描 + socket 补丁 |
| R-14 | 入站测试只允许 `httpx.ASGITransport` 驱动的 ASGI 调用；不得使用 Web 框架内置的同步测试客户端 | 测试静态扫描 |
| R-15 | 除 `backend/tests/test_webhook_e2e_offline.py` 中显式开关的可选回环用例外，任何新增测试不得调用 `uvicorn.run`、不得绑定端口 | `patch("socket.socket.bind")` 与静态扫描 |

### 1.3 任务回执模板（每个子任务完成必须回报，缺一不可）

```text
任务编号：
实际产出路径（绝对路径或仓库相对路径，逐条）：
验收项逐条结论（通过 / 不通过 + 证据）：
未修改清单（本任务未触碰的冻结文件与既有文件）：
下一任务编号与前置条件是否满足：
失败项与停止原因（无则写「无」）：
```

### 1.4 执行纪律

- [ ] 严格按任务编号顺序执行；被依赖任务未通过验收，不得开始后继任务。
- [ ] 任一验收项不通过即**停止**，提交失败报告，不得「跳过继续」或「先写后补」。
- [ ] 每个任务完成后必须按 1.3 模板回报；未回报视为未完成。
- [ ] 产品代码任务与测试任务严格分离：产品代码任务不得写测试文件，测试任务不得改产品代码（发现缺陷回到对应产品任务修复并重跑）。
- [ ] 所有命令在 `backend/` 目录下执行；Windows 环境优先 `python -m ...` 形式。
- [ ] 本阶段不写 `design.md`、`spec.md`、任何 `.md` 之外的既有文件；文档任务只允许新增 `docs/webhook_openapi_usage.md`。

### 1.5 依赖顺序总览

```text
1 基线
  → 2 integrations/models
  → 3 integrations/client
  → 4 integrations/openapi
  → 5 integrations/mock
  → 6 integrations/__init__
  → 7 webhook/models
  → 8 webhook/settings
  → 9 signature / 10 parser / 11 security / 12 idempotency / 13 render / 14 queue
  → 15 webhook/service
  → 16 webhook/routes
  → 17 webhook/app
  → 18 webhook/__init__ + __main__
  → 19 tests/helpers + fixtures
  → 20~27 八个测试文件（逐文件串行，按编号）
  → 28 导入与写操作审计
  → 29 回归与冻结门禁
  → 30 离线实测 / 零网络 / 零真实端口
  → 31 中文使用文档
  → 32 最终交付核对
```

**说明**：9～14 内部存在弱依赖（`parser` 依赖 `models`，`security` 依赖阶段 2 只读能力，`render` 依赖 `models` 与阶段 1 报告），可并行编码，但**验收与回报必须按编号顺序**；`queue` 与 `service` 存在构造依赖，`service` 必须在 14 通过后开始。

---

## 2. 冻结基线：改动前必须记录的证据

### 2.1 记录 310 条基线结果

- [ ] **执行基线测试并留证**
  - 前置依赖：无
  - 命令：`cd backend && python -m unittest discover -s tests -v`
  - 输入：当前工作区（零改动）
  - 输出：执行记录，必须包含 `Ran <N> tests`、`OK`/`FAILED`、`failures`、`errors`、`skipped` 四项计数
  - 拒绝口径：不得使用任何第三方测试运行器；不得只跑部分目录代替全量
  - 验收：
    1. `Ran 310 tests` 且总数记录为 310；
    2. 支持符号链接的环境为 `307 passed + 3 skipped`（1 条性能用例 + 2 条 Windows 符号链接平台用例），`reason` 逐条抄录；
    3. 当前沙箱若出现 2 条既有符号链接用例 failed/error，必须在记录中单列「既有平台异常」，写明用例名与原因，并注明**不纳入新增失败**；
    4. 记录中明确「新增 failed/error 基线 = 0」；
    5. 不修改任何测试文件、不修改 `backend/tests/__init__.py`。
  - 回执：按 1.3 模板，附命令原文与结果摘要。

### 2.2 记录 13 个冻结文件与关键零改动对象的 SHA-256

- [ ] **生成并保存改动前哈希清单**
  - 前置依赖：2.1
  - 冻结文件（13，仓库相对路径，逐一计算）：
    1. `backend/app/core/rules/engine.py`
    2. `backend/app/core/rules/naming.py`
    3. `backend/app/core/rules/code_scan.py`
    4. `backend/app/core/rules/link_check.py`
    5. `backend/app/core/rules/sensitive.py`
    6. `backend/app/core/rules/common/__init__.py`
    7. `backend/app/core/rules/common/config.py`
    8. `backend/app/core/rules/common/file_io.py`
    9. `backend/app/core/rules/common/manifest.py`
    10. `backend/app/core/rules/common/models.py`
    11. `backend/app/core/rules/common/report.py`
    12. `backend/app/core/rules/__init__.py`
    13. `backend/tests/test_cli.py`
  - 其他零改动对象：`backend/requirements.txt`、`backend/app/static/index.html`、`backend/tests/**` 除新增文件外全部、`backend/app/api/**`、`backend/app/health/**`、`backend/app/readme/**`、`backend/app/shared/**`
  - 命令（Windows 任选其一，逐文件执行）：
    - `certutil -hashfile <path> SHA256`
    - PowerShell：`Get-FileHash -Algorithm SHA256 <path>`
    - Git Bash / Linux：`sha256sum <path>`
  - 输出：`<sha256>  <repository-relative-path>` 形式的清单，存入本次执行记录（**不写入仓库**）
  - 验收：
    1. 13 条冻结文件哈希全部记录，无遗漏；
    2. `requirements.txt` 哈希必须等于 `18a816cd88636be844e7cd3a6662b2cdc2e13324420031f082a331a520b4bbcf`，行数 7；
    3. 记录 `tests/` 既有 17 个 `test_*.py` + `__init__.py` + `fixtures/sample_changes.txt` 的哈希；
    4. 记录 `static/index.html` 哈希；
    5. 清单为只读证据，不得提交进仓库、不得新增于 `backend/`。
  - 回执：按 1.3 模板，附清单条目数与 requirements 哈希值。

---

## 3. 集成层（`backend/app/integrations/`，5 个文件）

> 统一约束（适用于 3.1～3.5 全部文件）：
> 1. 首行 `from __future__ import annotations`；
> 2. 公开类型使用 `dataclass(frozen=True, slots=True)` 或 `Enum`；不使用 `Any`；集合优先 `tuple` / `Mapping`；
> 3. 异常类继承 `integrations.models.OpenApiError`；
> 4. 导入写法：`import fastapi`、`import httpx`、`import urllib.parse` 等模块导入；**禁止** `from httpx import ...`、`from fastapi import ...`、`from app...`、`from starlette... import ...`；
> 5. 不读环境变量以外的配置源，不写文件，不联网（除 `client.py` 的实现被调用时由上层决定目标）。

### 3.1 `backend/app/integrations/models.py`

- [ ] **新增集成层数据契约**
  - 完整路径：`backend/app/integrations/models.py`
  - 前置依赖：2.2
  - 输入：构造参数、profile、响应 JSON
  - 输出：冻结实例；缺失字段名元组；点分路径取值
  - 异常：`OpenApiError`（基类）、`OpenApiConfigError`（含 `missing_fields`）；参数非法时 `ValueError`
  - 允许依赖：`dataclasses`、`enum`、`typing`、`collections.abc`、`ipaddress`、`urllib.parse`（模块导入）
  - 公开签名（与 design 2.4.2（2）逐字一致）：
    ```python
    class OpenApiError(Exception):
        code: str
        status_code: int
        message: str
        detail: str | None

    class OpenApiConfigError(OpenApiError):
        missing_fields: "tuple[str, ...]"

    class OpenApiMode(Enum):
        DISABLED = "disabled"
        MOCK = "mock"
        LIVE = "live"

    class AuthScheme(Enum):
        BEARER = "bearer"
        HEADER = "header"
        NONE = "none"

    class CommentPayloadLike(Protocol):
        event_id: str
        repo_label: str
        pull_request_number: int
        markdown: str
        char_count: int
        byte_count: int
        truncated: bool
        omitted_must_fix: int
        omitted_suggestions: int
        marker: str
        check_status: str
        must_fix_count: int
        suggestion_count: int
        issue_count: int
        skipped_file_count: int
        degraded_module_count: int

    @dataclass(frozen=True, slots=True)
    class OpenApiProfile: ...

    @dataclass(frozen=True, slots=True)
    class PublishResult:
        success: bool
        status_code: int | None = None
        error_code: str | None = None
        error_message: str | None = None
        comment_id: str | None = None
        attempts: int = 1
        duration_ms: int = 0
        retried: bool = False

    def validate_profile(
        profile: OpenApiProfile | None, mode: OpenApiMode
    ) -> "tuple[str, ...]": ...

    def is_loopback_host(host: str) -> bool: ...

    def read_dot_path(payload: object, path: str) -> object | None: ...
    ```
  - 字段约束：`OpenApiProfile` 必须包含 design 2.3.3（8）表的 19 个字段，字段名、类型、默认值逐项一致，不得改名、不得少字段；`PublishResult` 8 字段一致。
  - 实现约束：
    1. `validate_profile()` 按 design 2.4.2（2）「模式 / 必填 / 额外校验」表返回**中文缺失项名**，只返回字段名，不含值、不含令牌；
    2. `live` 校验覆盖：`https`（loopback 例外）、无用户名密码/查询/片段、`allowed_hosts` 非空且无 `*` 且包含 `base_url` 主机、`verify_tls=False` 仅 loopback、`follow_redirects` 必须 `False`、`body_template` 含 `{markdown}`、endpoint 含 `{repo}`/`{pr_number}`、超时/重试/退避在范围内；
    3. `is_loopback_host()` 只认 `127.0.0.1`、`::1`、`localhost`（大小写不敏感），**不解析 DNS**；
    4. `read_dot_path()` 只接受字符串键映射与整数索引序列，失败返回 `None`，不抛异常；
    5. 无 I/O、无日志、无环境变量读取。
  - 验收：
    1. `python -m py_compile backend/app/integrations/models.py` 通过；
    2. 19 + 8 个字段名与 design 2.3.3 表逐项一致；
    3. `validate_profile(None, OpenApiMode.LIVE)` 返回非空且含 `base_url`、`comment_endpoint_template`、`body_template`、`allowed_hosts`、令牌项；
    4. `validate_profile(None, OpenApiMode.DISABLED)` 与 `validate_profile(None, OpenApiMode.MOCK)` 返回空元组；
    5. 文件内无 `fastapi`、`httpx` 导入，无文件写操作，无 `from ... import` 形式的第三方导入；
    6. `OpenApiConfigError.missing_fields` 为元组且不含任何配置值。
  - 回执：按 1.3 模板。

### 3.2 `backend/app/integrations/client.py`

- [ ] **新增可替换的出站 HTTP 通道**
  - 完整路径：`backend/app/integrations/client.py`
  - 前置依赖：3.1
  - 输入：方法、URL、头映射、内容字节、超时
  - 输出：`HttpResponse`
  - 异常：网络异常向上抛（`httpx` 异常类型，由适配器分类）；参数非法 `ValueError`；`close()` 不抛异常
  - 允许依赖：`httpx`（模块导入）、`dataclasses`、`typing`、`collections.abc`、`.models`
  - 公开签名（与 design 2.4.2（3）逐字一致）：
    ```python
    @dataclass(frozen=True, slots=True)
    class HttpResponse:
        status_code: int
        headers: "Mapping[str, str]"
        content: bytes
        elapsed_ms: float
        content_truncated: bool = False

    class HttpClient(Protocol):
        def request(
            self,
            method: str,
            url: str,
            *,
            headers: "Mapping[str, str]",
            content: bytes | None,
            timeout: float,
        ) -> HttpResponse: ...

    class HttpxHttpClient:
        def __init__(
            self,
            *,
            transport: "httpx.BaseTransport | None" = None,
            verify_tls: bool = True,
            user_agent: str = "RepoGuard-Webhook/1.0",
        ) -> None: ...

        def request(
            self,
            method: str,
            url: str,
            *,
            headers: "Mapping[str, str]",
            content: bytes | None,
            timeout: float,
        ) -> HttpResponse: ...

        def close(self) -> None: ...

    def build_http_client(
        profile: OpenApiProfile, *, transport: "httpx.BaseTransport | None" = None
    ) -> HttpClient: ...
    ```
  - 实现约束：
    1. `httpx.Client(verify=..., follow_redirects=False, timeout=..., transport=transport)`；
    2. 请求头只允许 `Content-Type`、`User-Agent`、认证头、`Accept`；**不得发送** `Cookie`、`Referer`、`Origin`；
    3. 响应体超过 65,536 字节截断并置 `content_truncated=True`；
    4. `elapsed_ms` 用 `time.perf_counter()`（需 `import time`）；
    5. `transport` 仅测试注入 `httpx.MockTransport`；生产不传；
    6. `close()` 释放连接池且不抛异常。
  - 验收：
    1. `python -m py_compile backend/app/integrations/client.py` 通过；
    2. 以 `httpx.MockTransport` 注入可返回内存响应，`HttpResponse` 字段齐全；
    3. 构造客户端后无任何真实连接；`build_http_client` 返回 `HttpClient` 协议实现；
    4. 文件内无 `from httpx import ...`、无 `from app...`；
    5. 不读环境变量、不写文件。
  - 回执：按 1.3 模板。

### 3.3 `backend/app/integrations/openapi.py`

- [ ] **新增可配置 OpenAPI 出站适配器**
  - 完整路径：`backend/app/integrations/openapi.py`
  - 前置依赖：3.1、3.2
  - 输入：`OpenApiProfile`、`HttpClient`、`clock`、`sleeper`、`env`、可选 `token`
  - 输出：`PublishResult`、`tuple[str, ...] | None`
  - 异常：构造期 `OpenApiConfigError`；运行期一律转为 `PublishResult` / `None`，不抛业务异常；主机越界转为 `PublishResult(error_code="OPENAPI_HOST_FORBIDDEN")`
  - 允许依赖：`urllib.parse`（模块导入）、`json`、`ipaddress`、`random`（模块导入）、`time`、`os`、`dataclasses`、`typing`、`collections.abc`、`.client`、`.models`
  - 公开签名（与 design 2.4.2（4）逐字一致）：
    ```python
    class OpenApiAdapter(Protocol):
        def fetch_changed_files(
            self, repo: str, base_sha: str, head_sha: str
        ) -> "tuple[str, ...] | None": ...

        def publish_comment(
            self, repo: str, pr_number: int, payload: CommentPayloadLike
        ) -> PublishResult: ...

    class ConfigurableOpenApiAdapter:
        def __init__(
            self,
            profile: OpenApiProfile,
            *,
            client: "HttpClient | None" = None,
            clock: "Callable[[], float] | None" = None,
            sleeper: "Callable[[float], None] | None" = None,
            env: "Mapping[str, str] | None" = None,
            token: str | None = None,
        ) -> None: ...

        def fetch_changed_files(
            self, repo: str, base_sha: str, head_sha: str
        ) -> "tuple[str, ...] | None": ...

        def publish_comment(
            self, repo: str, pr_number: int, payload: CommentPayloadLike
        ) -> PublishResult: ...

        def close(self) -> None: ...
    ```
  - 实现约束：
    1. 构造期先 `validate_profile(profile, OpenApiMode.LIVE)`；缺失 → `OpenApiConfigError(code="OPENAPI_NOT_CONFIGURED", status_code=503, missing_fields=...)`；
    2. 令牌来源优先级：`token` 参数 → `env[profile.token_env]`；`auth_scheme != NONE` 且为空 → `OpenApiConfigError`（缺失项 `token_env`）；令牌只存私有属性，`__repr__` 不输出；
    3. URL：`urljoin(base_url.rstrip("/") + "/", template)`；`{repo}` 用 `urllib.parse.quote(repo, safe="/")`；`{pr_number}` 十进制；未知占位保持字面量；**不得原样拼接 repo**；
    4. URL 校验：scheme 仅 `https`（`http` 仅 loopback）、无凭据、`base_url` 无 query/fragment、`hostname` 精确命中 `allowed_hosts`（大小写不敏感、禁止后缀匹配与 `*`）；IP 字面量拒绝 private/loopback（loopback 且 http/https 允许）/link-local/multicast/reserved/`169.254.169.254`；失败不发请求；
    5. 请求体：`body_template` 中 `{markdown}` 用 `json.dumps(payload.markdown, ensure_ascii=False)` 的带引号字符串替换，替换后必须 `json.loads` 为对象，否则 `PublishResult(success=False, error_code="OPENAPI_NOT_CONFIGURED", error_message="评论请求体模板不合法")` 且不发起请求；
    6. 认证头：`bearer` → `Authorization: Bearer <token>`（`auth_header` 可覆盖头名）；`header` → `<auth_header>: <auth_prefix><token>`；`none` → 不发送；
    7. 重试：`attempts = max_retries + 1`，总预算 30 秒固定；单次 `timeout = min(timeout_seconds, max(0.1, remaining))`；可重试连接/TLS/超时/429/5xx；不重试 3xx、400/413、401/403、404、其他 4xx；退避 `base * 2**(n-1)` 带 `±20%` 抖动，`sleeper(seconds)`，sleep 前检查预算；重试复用同一字节，不重新渲染；
    8. 结果映射严格按 design 2.5.6（5）表：成功状态码 → `success=True`；401/403 → `OPENAPI_AUTH_FAILED`；404 → `OPENAPI_NOT_FOUND`；3xx → `OPENAPI_REDIRECT_FORBIDDEN`；400/413 → `OPENAPI_COMMENT_TOO_LONG`；429/5xx 耗尽 → `OPENAPI_UNAVAILABLE`；超时/预算耗尽 → `OPENAPI_TIMEOUT`；连接/DNS/TLS → `OPENAPI_UNAVAILABLE`；主机越界 → `OPENAPI_HOST_FORBIDDEN`；配置不完整 → `OPENAPI_NOT_CONFIGURED`；2xx 但响应不可解析 → `success=True` 且 `comment_id=None`；
    9. 失败 `error_message` 为固定中文，不含平台响应体全文、不含令牌、不含 URL 凭据；
    10. `fetch_changed_files()`：endpoint 为空或 sha 缺失 → `None` 且不发请求；GET 单次请求不重试、超时 `min(timeout_seconds, 10)`；非 2xx/超时/连接失败/解析失败/截断/路径缺失或类型不符 → `None`；成功返回 `tuple(str(item) ...)`；空数组 → `()`。
  - 验收：
    1. `python -m py_compile backend/app/integrations/openapi.py` 通过；
    2. 所有平台细节来自 `OpenApiProfile`，文件内无硬编码 endpoint、无硬编码主机、无硬编码令牌；
    3. 以 `httpx.MockTransport` 驱动可得 `PublishResult`，且在无 `client` 时由 `build_http_client` 构造；
    4. `publish_comment()` 不抛业务异常；`fetch_changed_files()` 不抛业务异常；
    5. 令牌不出现在 `repr`、日志、`PublishResult` 任何字段；
    6. 无 `from httpx import ...`、无 `from app...`。
  - 回执：按 1.3 模板。

### 3.4 `backend/app/integrations/mock.py`

- [ ] **新增离线模拟出站能力（内存适配器 + 进程内 mock 服务）**
  - 完整路径：`backend/app/integrations/mock.py`
  - 前置依赖：3.1、3.3（仅共享 `OpenApiAdapter` 协议与模型）
  - 输入：预置变更清单、预置 `PublishResult` 序列、ASGI 请求
  - 输出：`PublishResult`、`tuple[str, ...] | None`、请求记录、评论记录
  - 异常：构造期非法参数 `ValueError`；运行期不抛业务异常
  - 允许依赖：`fastapi`（模块导入）、`json`、`threading`（模块导入）、`dataclasses`、`typing`、`collections.abc`、`httpx`（仅 `ASGITransport` 类型）、`.models`
  - 公开签名（与 design 2.4.2（5）逐字一致）：
    ```python
    @dataclass(frozen=True, slots=True)
    class MockRequest:
        method: str
        url: str
        headers: "Mapping[str, str]"
        body: bytes

    class MockOpenApiAdapter:
        def __init__(
            self,
            *,
            changed_files: "tuple[str, ...] | None" = None,
            publish_results: "Sequence[PublishResult] | None" = None,
            clock: "Callable[[], float] | None" = None,
        ) -> None: ...

        def fetch_changed_files(
            self, repo: str, base_sha: str, head_sha: str
        ) -> "tuple[str, ...] | None": ...

        def publish_comment(
            self, repo: str, pr_number: int, payload: CommentPayloadLike
        ) -> PublishResult: ...

        @property
        def comments(self) -> "tuple[CommentPayloadLike, ...]": ...

        @property
        def requests(self) -> "tuple[MockRequest, ...]": ...

    class MockOpenApiService:
        def __init__(self, profile: OpenApiProfile | None = None) -> None: ...

        @property
        def app(self) -> "fastapi.FastAPI": ...

        @property
        def requests(self) -> "tuple[MockRequest, ...]": ...

        def transport(self) -> "httpx.ASGITransport": ...

    def build_mock_service(profile: OpenApiProfile | None = None) -> MockOpenApiService: ...
    ```
  - 实现约束：
    1. `MockOpenApiAdapter`：`changed_files=None` → `None`；`()` → `()`；非空 → 预置元组；`publish_results` 为空 → 默认 `PublishResult(success=True, status_code=201, comment_id="mock-comment-<n>")`，非空按序消费、耗尽后重复最后一个；每次调用追加请求记录；列表与游标用 `threading.Lock` 保护；无网络/无文件/无端口；
    2. `MockOpenApiService`：独立 `fastapi.FastAPI`，路由 `POST /mock/repos/{repo:path}/pulls/{pr_number}/comments` → 201 `{"data":{"id":"mock-comment-<n>"}}`，`GET /mock/repos/{repo:path}/compare?base=&head=` → 200 `{"data":{"changed_files":[...]}}`；不注册到 Webhook 应用；
    3. `transport()` 返回 `httpx.ASGITransport(app=self.app)`；**不得**调用 `uvicorn.run`、不得绑定端口；
    4. 请求记录含方法、URL、头名（**不记录认证头值**）、请求体长度；
    5. `profile` 仅用于把 endpoint 模板映射到 `/mock` 前缀。
  - 验收：
    1. `python -m py_compile backend/app/integrations/mock.py` 通过；
    2. `MockOpenApiAdapter` 的 `comments`、`requests` 在多次调用后计数正确且并发安全；
    3. `MockOpenApiService.transport()` 可被 `httpx.AsyncClient` 驱动并返回 201/200 契约响应；
    4. 整个文件无真实 socket 创建、无端口绑定、无文件写；
    5. 未导入 `app.webhook.**`（避免反向依赖），未使用 `from fastapi import ...`。
  - 回执：按 1.3 模板。

### 3.5 `backend/app/integrations/__init__.py`

- [ ] **落定集成层公共导出**
  - 完整路径：`backend/app/integrations/__init__.py`
  - 前置依赖：3.1、3.3、3.4
  - 输入：无
  - 输出：`__all__` 元组与再导出符号
  - 异常：仅标准 `ImportError`，不做兜底吞异常
  - 允许依赖：`.models`、`.openapi`
  - 公开签名（与 design 2.4.2（1）逐字一致）：
    ```python
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
    ```
  - 实现约束：**不得导入 `.mock`**（避免仅需配置模型时引入 `fastapi`）；导入后无环境变量读取、无副作用、无线程。
  - 验收：
    1. `python -m py_compile backend/app/integrations/__init__.py` 通过；
    2. `python -c "import app.integrations"` 在 `backend/` 下成功且不触发 `fastapi`/`httpx` 导入；
    3. `__all__` 与签名逐字一致；
    4. 无 `from app...`。
  - 回执：按 1.3 模板。

---

## 4. Webhook 包（`backend/app/webhook/`，13 个文件）

> 统一约束（适用于 4.1～4.12 全部文件）：
> 1. 首行 `from __future__ import annotations`；公开类型 `dataclass(frozen=True, slots=True)` 或 `Enum`；不使用 `Any`；
> 2. 业务异常继承 `models.WebhookError`，出站异常继承 `integrations.models.OpenApiError`；
> 3. 绝对导入只允许模块形式（`import fastapi`、`import hmac`、`import hashlib`、`import threading`、`import queue`、`import concurrent.futures`、`import uvicorn`、`import starlette.responses`、`import starlette.exceptions`）；**禁止** `from fastapi import ...`、`from httpx import ...`、`from starlette... import ...`、`from app...`；
> 4. 相对导入允许 `..core.rules.engine`、`..core.rules.common.models`、`..core.rules.common.report`、`..core.rules.common.config`、`..api.settings`、`..api.security`、`..integrations.*`、`.models`、`.settings` 等；相对导入首段**不得**为 `naming`、`code_scan`、`link_check`、`sensitive`、`engine`；
> 5. 不得导入 `app.health.*`、`app.readme.*`、`app.shared.*`、`app.api.routes`、`app.api.app`；
> 6. 不得出现 `subprocess`、`os.system`、`os.popen`、`git clone/fetch/pull`；不写被检查仓库；不执行被检查代码。

### 4.1 `backend/app/webhook/models.py`

- [ ] **新增 Webhook 数据模型与统一异常**
  - 完整路径：`backend/app/webhook/models.py`
  - 前置依赖：3.1
  - 输入：构造参数
  - 输出：冻结实例
  - 异常：`ValueError`（构造期字段非法）、`WebhookError`（业务异常基类）
  - 允许依赖：`dataclasses`、`enum`、`typing`、`pathlib`、`datetime`、`..integrations.models`（仅 `PublishResult` 类型）
  - 公开签名（与 design 2.4.1（4）逐字一致）：
    ```python
    class WebhookError(Exception):
        def __init__(self, code: str, status_code: int, message: str, detail: str | None = None) -> None: ...
        code: str
        status_code: int
        message: str
        detail: str | None

    class EventKind(Enum):
        CREATED = "created"
        UPDATED = "updated"

    class ChangedFilesSource(Enum):
        PAYLOAD = "payload"
        PAYLOAD_LISTS = "payload_lists"
        OPENAPI = "openapi"
        NONE = "none"

    class CheckOutcome(Enum):
        OK = "正常"
        PARTIAL_DEGRADED = "部分降级"
        INPUT_ERROR = "输入错误"
        NOT_EXECUTED = "未执行"
        TIMEOUT = "超时"
        FAILED = "失败"

    class DeliveryStatus(Enum):
        DELIVERED = "delivered"
        MOCK_DELIVERED = "mock_delivered"
        SKIPPED = "skipped"
        SKIPPED_DUPLICATE = "skipped_duplicate"
        FAILED = "failed"
        DEGRADED = "degraded"
        NOT_ATTEMPTED = "not_attempted"

    @dataclass(frozen=True, slots=True)
    class WebhookEvent: ...
    @dataclass(frozen=True, slots=True)
    class NormalizedEvent: ...
    @dataclass(frozen=True, slots=True)
    class ReviewJob: ...
    @dataclass(frozen=True, slots=True)
    class CommentPayload: ...
    @dataclass(frozen=True, slots=True)
    class DeliveryRecord: ...
    @dataclass(frozen=True, slots=True)
    class IngestOutcome: ...
    @dataclass(frozen=True, slots=True)
    class HealthSnapshot: ...

    def utc_now() -> "datetime": ...
    def format_utc(value: "datetime") -> str: ...
    ```
  - 字段约束（全部以 design 2.3.3 表为准，不得增删改名）：
    1. `WebhookEvent`：design 2.3.3（1）12 字段；
    2. `NormalizedEvent`：design 2.3.3（2）13 字段；
    3. `ReviewJob`：design 2.3.3（3）7 字段；
    4. `CommentPayload`：design 2.3.3（4）16 字段；
    5. `DeliveryRecord`：design 2.3.3（6）表全部字段（含 `publish_result`、`error_code`、`reason`）；
    6. `IngestOutcome`：`status_code`、`body`、`error_code`；
    7. `HealthSnapshot`：design 2.2.2（2）13 字段。
  - 实现约束（`__post_init__` 校验，逐项）：
    1. `WebhookEvent`：`1 <= len(event_id) <= 200`；`1 <= len(event_type) <= 100`；`action` ≤ 50；`1 <= len(repository_identifier) <= 300`；PR > 0；`body_sha256` 匹配 `^[0-9a-f]{64}$`；`event_id_source` 属于三值；
    2. `NormalizedEvent`：`event_kind` 为枚举；`changed_files_source` 四值；`signature_verified is True`；`repo_label` 不含 `/`、`\`、`:`；
    3. `ReviewJob`：`entry_count == len([行 for 行 in manifest_text.splitlines() if 行])`；`attempt >= 1`；`1 <= len(request_id) <= 64`；
    4. `CommentPayload`：`1 <= len(markdown) <= 100_000`；计数非负；`marker` 必须在 `markdown` 末尾；
    5. `DeliveryRecord`：六态 `check_status`、七态 `delivery_status`；`duration_ms >= 0`；
    6. `IngestOutcome`：`status_code` 为合法 HTTP 码；
    7. `HealthSnapshot`：`status` 仅 `ok/degraded`；`service == "repoguard-webhook"`；`version == "1.0.0"`。
  - 验收：
    1. `python -m py_compile backend/app/webhook/models.py` 通过；
    2. 7 个异常/枚举 + 7 个 dataclass 全部存在，字段与 design 2.3.3 逐项一致；
    3. 每类非法构造（空 `event_id`、非 64 位哈希、`signature_verified=False`、`stop_timeout` 越界、`status` 非法等）均抛 `ValueError`，不静默修正；
    4. 文件无 I/O、无线程、无网络、无日志、无环境变量；
    5. 只允许 `..integrations.models` 一个跨包导入。
  - 回执：按 1.3 模板。

### 4.2 `backend/app/webhook/settings.py`

- [ ] **新增 Webhook 运行配置加载**
  - 完整路径：`backend/app/webhook/settings.py`
  - 前置依赖：4.1
  - 输入：`env: Mapping[str, str] | None`（`None` 读 `os.environ`）
  - 输出：归一化 `WebhookConfig`、`OpenApiProfile | None`、摘要字典
  - 异常：**不向外抛配置异常**；安全相关缺失保留为空并在健康检查降级，不回退为「放行」
  - 允许依赖：`os`、`json`、`re`、`dataclasses`、`typing`、`collections.abc`、`.models`、`..integrations.models`
  - 公开签名（与 design 2.4.1（3）逐字一致）：
    ```python
    class ConfigError(Exception):
        field: str
        message: str

    def default_config() -> WebhookConfig: ...

    def normalize_config(config: WebhookConfig) -> WebhookConfig: ...

    def load_webhook_config(env: "Mapping[str, str] | None" = None) -> WebhookConfig: ...

    def load_openapi_profile(env: "Mapping[str, str] | None" = None) -> "OpenApiProfile | None": ...

    def validate_webhook_path(path: str) -> str: ...

    def config_summary(config: WebhookConfig) -> "dict[str, object]": ...
    ```
  - 字段约束：`WebhookConfig` 必须包含 design 2.3.3（7）的 34 个字段（30 个 spec 字段 + `idempotency_retry_failed`、`stop_timeout_seconds`、`duplicate_comment_check`、`event_kind_map`），默认值与范围逐项一致。
  - 实现约束：
    1. `normalize_config()` 数值越界/非法回退默认并 `logging.warning` 中文；`path` 非法回退 `/webhook`；`host` 非法回退 `127.0.0.1`；`port` 非法回退 `8010`；`openapi_mode` 非法回退 `disabled`；`max_comment_chars` 越界回退 60,000；`worker_concurrency` 越界回退 2；
    2. `load_webhook_config()` 逐字段读取 `REPOGUARD_WEBHOOK_*` 与 `REPOGUARD_OPENAPI_*` / `REPOGUARD_ALLOWED_REPOS` / `REPOGUARD_DEFAULT_REPO`（后两者只读复用，不新增第二套白名单）；布尔只接受 `1/0/true/false/yes/no`（大小写不敏感）；`field_map`/`repo_map`/`event_kind_map` 用 JSON 对象；解析失败回退默认并告警；
    3. `load_openapi_profile()` 仅在 `openapi_mode != disabled` 时构造；缺项仍返回 profile（字段为空），由 `validate_profile()` 判定，便于健康检查列出缺失项；
    4. `validate_webhook_path()`：`/` 开头、长度 1～64、无 `..` 段、无控制字符、不以 `//` 开头；
    5. `config_summary()` 只含 `enabled/host/port/path/openapi_mode/replay_window/queue_capacity/worker_concurrency/max_body_bytes/secret_configured/token_configured`；**不含密钥、令牌、模板原文、绝对路径**；
    6. `secret`/`token` 含控制字符视为未配置；
    7. 不导入 `app.api.settings`（白名单由 service/security 侧读取，避免配置层耦合）。
  - 验收：
    1. `python -m py_compile backend/app/webhook/settings.py` 通过；
    2. `default_config()` 与 design 2.3.3（7）默认值逐项一致，`host == "127.0.0.1"`、`port == 8010`、`openapi_mode == DISABLED`；
    3. 注入非法值（负端口、`max_body_bytes=1`、`replay_window=10`、非法布尔、损坏 JSON、`path="../x"`、含控制字符的 secret）后全部回退默认且产生中文告警，不抛异常；
    4. `config_summary()` 序列化后不包含密钥、令牌、绝对路径、模板原文（用固定假密钥断言子串不出现）；
    5. `load_openapi_profile(env)` 在 `disabled` 下返回 `None`，`live` 下返回 profile 且缺项字段为空；
    6. 文件内无 `from app...`，无文件写操作。
  - 回执：按 1.3 模板。

### 4.3 `backend/app/webhook/signature.py`

- [ ] **新增入站验签与重放防护**
  - 完整路径：`backend/app/webhook/signature.py`
  - 前置依赖：4.2
  - 输入：请求头映射、原始字节、配置、可控时钟
  - 输出：`SignatureResult`
  - 异常：`SignatureError`（继承 `WebhookError`），`code` 与状态码按 design 2.4.1（5）表
  - 允许依赖：`hmac`（模块导入）、`hashlib`（模块导入）、`re`、`time`、`typing`、`collections.abc`、`.models`、`.settings`
  - 公开签名（与 design 2.4.1（5）逐字一致）：
    ```python
    class SignatureError(WebhookError): ...

    @dataclass(frozen=True, slots=True)
    class SignatureResult:
        ok: bool
        used_previous: bool
        timestamp_seconds: int
        skew_seconds: int
        timestamp_unit: str

    def build_signature(secret: str, timestamp_header_value: str, raw_body: bytes) -> str: ...

    def parse_signature_header(value: str | None, prefix: str) -> str: ...

    def parse_timestamp(
        value: str | None, now: float, window_seconds: int
    ) -> "tuple[int, int, str]": ...

    def verify_signature(
        headers: "Mapping[str, str]",
        raw_body: bytes,
        config: WebhookConfig,
        now: float | None = None,
    ) -> SignatureResult: ...

    def secret_configured(config: WebhookConfig) -> bool: ...
    def has_control_chars(value: str) -> bool: ...
    ```
  - 实现约束：
    1. 签名串固定 `timestamp_header_value.strip() + "." + raw_body`；算法固定 HMAC-SHA256；输出 64 位小写 hex；**只用 `hmac.compare_digest()`**；
    2. `verify_signature()` 按 design 2.4.1（5）8 步固定顺序与错误映射：
       - 密钥为空/纯空白 → `WEBHOOK_SECRET_NOT_CONFIGURED` / 503（且不读取请求体）
       - 签名头缺失/空白 → `WEBHOOK_SIGNATURE_MISSING` / 401
       - 时间戳头缺失/空白 → `WEBHOOK_TIMESTAMP_MISSING` / 401
       - 时间戳非纯数字/为负/非 10 或 13 位/超前超窗 → `WEBHOOK_TIMESTAMP_INVALID` / 401
       - 落后超窗 → `WEBHOOK_TIMESTAMP_EXPIRED` / 401
       - 前缀不符/长度非 64/非十六进制 → `WEBHOOK_SIGNATURE_INVALID` / 401
       - 当前与上一版本均不匹配 → `WEBHOOK_SIGNATURE_INVALID` / 401
       - 通过 → `SignatureResult(ok=True, ...)`
    3. 13 位毫秒按原样参与签名，仅窗口校验换算；`timestamp_unit` 取 `"seconds"`/`"milliseconds"`；
    4. 密钥轮换：先当前密钥，失败且 `secret_previous` 非空再比较一次；上一版本命中 `used_previous=True`；
    5. 不记录期望签名、不记录密钥、不记录长度/字符集；不区分「当前密钥不匹配」与「上一版本不匹配」的响应；
    6. 中文 `message` 与 design 表逐字一致。
  - 验收：
    1. `python -m py_compile backend/app/webhook/signature.py` 通过；
    2. 每个错误分支返回唯一 `code` 与 `status_code`，中文文案与 design 2.4.1（5）表一致；
    3. 篡改 1 字节、错误前缀、长度 63/65、非 hex、`now` 注入对照窗口边界（`skew == ±window` 通过）全部符合；
    4. 上一版本密钥通过时 `used_previous=True`；两次都不匹配时响应文案不区分版本；
    5. 文件内无 `from hmac import ...`、`from hashlib import ...`，无日志输出密钥内容。
  - 回执：按 1.3 模板。

### 4.4 `backend/app/webhook/parser.py`

- [ ] **新增事件解析、归一化与变更清单构造**
  - 完整路径：`backend/app/webhook/parser.py`
  - 前置依赖：4.2
  - 输入：原始字节、请求头、配置
  - 输出：`WebhookEvent`、`NormalizedEvent`、`(manifest_text, entry_count)`
  - 异常：`EventParseError`（继承 `WebhookError`）：400 `WEBHOOK_INVALID_JSON` 或 422 `WEBHOOK_EVENT_INVALID`
  - 允许依赖：`json`、`re`、`hashlib`（模块导入）、`typing`、`collections.abc`、`pathlib`、`.models`、`.settings`
  - 公开签名（与 design 2.4.1（6）逐字一致）：
    ```python
    class EventParseError(WebhookError): ...

    def decode_json_object(raw_body: bytes) -> "Mapping[str, object]": ...

    def read_field(
        payload: "Mapping[str, object]", paths: "Sequence[str]"
    ) -> object | None: ...

    def detect_event_type(
        headers: "Mapping[str, str]",
        payload: "Mapping[str, object]",
        config: WebhookConfig,
    ) -> str: ...

    def classify_event_kind(
        event_type: str, config: WebhookConfig
    ) -> "EventKind | None": ...

    def is_action_allowed(action: str | None, kind: EventKind) -> bool: ...

    def compute_event_id(
        payload: "Mapping[str, object]",
        headers: "Mapping[str, str]",
        body_sha256: str,
        config: WebhookConfig,
    ) -> "tuple[str, str]": ...

    def parse_event(
        raw_body: bytes,
        headers: "Mapping[str, str]",
        config: WebhookConfig,
    ) -> WebhookEvent: ...

    def normalize_event(
        event: WebhookEvent, config: WebhookConfig, repo_label: str
    ) -> NormalizedEvent: ...

    def extract_changed_files(
        payload: "Mapping[str, object]", config: WebhookConfig
    ) -> "tuple[tuple[str, ...], ChangedFilesSource]": ...

    def normalize_changed_path(raw: str) -> "tuple[str | None, str | None]": ...

    def build_manifest(
        paths: "Sequence[str]", statuses: "Mapping[str, str] | None" = None
    ) -> "tuple[str, int]": ...

    def content_hash(
        event_type: str,
        repository_identifier: str,
        pull_request_number: int,
        base_sha: str | None,
        head_sha: str | None,
        raw_body: bytes,
    ) -> str: ...

    def should_fetch_via_openapi(
        normalized: NormalizedEvent, config: WebhookConfig
    ) -> bool: ...
    ```
  - 实现约束：
    1. `parse_event()` 8 步：`body_sha256` → `decode_json_object()`（空体/截断/非 UTF-8/非 JSON/顶层非对象 → 400）→ `detect_event_type()`（头优先，payload 回退，失败 422）→ `compute_event_id()`（payload → 投递头 → content_hash，记录来源）→ 字段映射 → 必填校验（仓库标识、PR、SHA 7～64 hex、action 字符串，失败 422 且 `detail` 只含字段名）→ 头过滤（只保留配置声明的四类头，大小写不敏感，禁止保留 `Authorization`/`Cookie`）→ 返回 `WebhookEvent`（`received_at = utc_now()`）；
    2. `normalize_event()` 6 步：`classify_event_kind()`（`event_kind_map` 优先，否则按事件类型最后一段判定，无法判定 422）→ `is_action_allowed()`（允许 `None`、`opened/created/updated/edited/synchronize/synchronized/reopened/ready_for_review`，其余返回 `ignored`）→ `extract_changed_files()` 按 design 2.5.2（4）优先级 → 逐条 `normalize_changed_path()`（去重保序，非法入 `illegal_paths`）→ `changed_files_available` 与 `should_fetch_via_openapi()` → `signature_verified=True`、`occurred_at`；
    3. `normalize_changed_path()` 严格按 design 2.4.1（6）表 9 种形态（空、`./`、`\`、UNC/设备、绝对/盘符、`..`、控制字符、> 512、含空格保留）；
    4. 路径处理顺序按 design 2.5.2（5）12 步（折叠 `/`、去末尾 `/`、段校验、小写盘符以外保持原样）；
    5. `build_manifest()`：每行「`A`/`M`/`D` + 一个空格 + 路径」，无注释/空行/额外字段，末尾保留一个 `\n`，`entry_count == 行数`，路径空格不转义不引号；
    6. `content_hash()` 输入顺序与分隔符与 design 2.5.2（3）逐字一致；同一 payload 两次相同、不同 body 不同；
    7. `extract_changed_files()`：`changed_files` 空数组视为缺失；`added/modified/removed` 至少 1 条合法则用；全非法 → `available=False`；缺失且 OpenAPI 条件满足 → `openapi`；否则 `none`；
    8. `should_fetch_via_openapi()`：endpoint 模板已配置 + 两个 sha 均存在 + 模式非 `disabled`；
    9. 不猜测、不 `str()` 强转、不从 URL 推导、不修改 payload。
  - 验收：
    1. `python -m py_compile backend/app/webhook/parser.py` 通过；
    2. 400 与 422 分支的错误码、状态码、`detail` 字段规范与 design 一致；
    3. 四类变更清单来源判定（`payload`/`payload_lists`/`openapi`/`none`）与合法路径计数正确；
    4. 9 种路径形态逐条符合 design 表，非法路径不进入 `manifest_text`；
    5. `build_manifest()` 在含空格路径、空列表、5000 条边界下格式与计数正确；
    6. 文件内无 `from hashlib import ...`、无文件写、无 `subprocess`。
  - 回执：按 1.3 模板。

### 4.5 `backend/app/webhook/security.py`

- [ ] **新增仓库映射与统一脱敏**
  - 完整路径：`backend/app/webhook/security.py`
  - 前置依赖：4.2
  - 输入：仓库标识、`WebSettings`、`WebhookConfig`、待脱敏文本/头映射
  - 输出：`Path`、脱敏字符串、过滤后的头映射
  - 异常：`RepoMappingError`（继承 `WebhookError`，403 `WEBHOOK_REPO_FORBIDDEN`）
  - 允许依赖：`pathlib`、`re`、`typing`、`collections.abc`、`..api.settings`、`..api.security`、`.models`、`.settings`
  - 公开签名（与 design 2.4.1（7）逐字一致）：
    ```python
    class RepoMappingError(WebhookError): ...

    def candidate_repo_tokens(identifier: str) -> "tuple[str, ...]": ...

    def resolve_event_repo(
        identifier: str,
        web_settings: "WebSettings",
        config: WebhookConfig,
    ) -> "Path": ...

    def safe_repo_label(identifier: str) -> str: ...

    def redact_text(
        text: str,
        secrets: "Sequence[str]" = (),
        absolute_roots: "Sequence[str]" = (),
    ) -> str: ...

    def redact_headers(
        headers: "Mapping[str, str]", keep: "Sequence[str]"
    ) -> "Mapping[str, str]": ...
    ```
  - 实现约束：
    1. 映射顺序（大小写不敏感）：`repo_map` 键匹配整串或末段 → 末段 → 原值；逐候选调用阶段 2 的 `resolve_repo_root(token, web_settings)`；全部 `RepoPathError` → `RepoMappingError("WEBHOOK_REPO_FORBIDDEN", 403, "仓库不在服务端允许范围内")`，`detail=None`；
    2. **禁止**自行比较 `Path` 公共前缀、自行 `Path(token).resolve()`、透出 `RepoPathError` 的 `code/message/detail`、映射失败时尝试下载仓库；
    3. `safe_repo_label()`：取末段；为空或含路径分隔符/控制字符 → `hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8]`（需 `import hashlib` 模块形式）；
    4. `redact_text()` 替换目标与正则按 design 2.4.1（7）表：密钥/令牌字面量（长度 ≥ 4，长值优先）、Bearer 片段、Windows 绝对路径、UNC/设备路径、用户主目录、已知绝对根；统一替换为 `****`；
    5. `redact_headers()` 只保留 `keep` 中声明的头（大小写不敏感），其余丢弃；返回只读映射。
  - 验收：
    1. `python -m py_compile backend/app/webhook/security.py` 通过；
    2. 白名单内三种映射（全名、短名、`repo_map`）均返回真实白名单根；白名单外返回 403 且无文件系统探测行为；
    3. 映射失败时响应 `detail=None`，不泄露白名单内容；
    4. `redact_text()` 对固定假密钥、假令牌、`C:\repo\a.py`、`/home/user/x`、`\\server\share` 全部替换为 `****`，且不保留长度信息；
    5. 仅导入 `..api.settings`、`..api.security`，未导入 `app.api.routes`、`app.api.app`；
    6. 无 `subprocess`、无 `os.system`、无远程仓库操作。
  - 回执：按 1.3 模板。

### 4.6 `backend/app/webhook/idempotency.py`

- [ ] **新增单进程内存幂等去重**
  - 完整路径：`backend/app/webhook/idempotency.py`
  - 前置依赖：4.1
  - 输入：`event_id`、`body_sha256`、开关、当前时间
  - 输出：`ReservationResult`、规模与淘汰计数
  - 异常：不抛业务异常；非法参数 `ValueError`
  - 允许依赖：`threading`（模块导入）、`time`、`collections`、`dataclasses`、`enum`、`typing`
  - 公开签名（与 design 2.4.1（8）逐字一致）：
    ```python
    class ReservationState(Enum):
        NEW = "new"
        RETRY_ALLOWED = "retry_allowed"
        DUPLICATE_PROCESSING = "duplicate_processing"
        DUPLICATE_DONE = "duplicate_done"
        DUPLICATE_FAILED = "duplicate_failed"
        CONFLICT = "conflict"

    class ReservationResult:
        state: ReservationState
        attempt: int
        first_seen: float
        body_sha256: str
        previous_state: str | None
        error_code: str | None

    class IdempotencyRegistry:
        def __init__(
            self,
            ttl_seconds: int,
            capacity: int,
            *,
            stale_after_seconds: float = 150.0,
            clock: "Callable[[], float] | None" = None,
        ) -> None: ...

        @property
        def size(self) -> int: ...
        @property
        def evicted_count(self) -> int: ...

        def reserve(
            self,
            event_id: str,
            body_sha256: str,
            *,
            allow_retry_failed: bool = False,
        ) -> ReservationResult: ...

        def complete(self, event_id: str) -> None: ...
        def fail(self, event_id: str, error_code: str) -> None: ...
        def rollback(self, event_id: str, previous_state: str | None) -> None: ...
        def purge(self) -> int: ...
        def snapshot(self) -> "dict[str, int]": ...
    ```
  - 实现约束：
    1. `reserve()` 判定严格按 design 2.4.1（8）表：不存在/过期/陈旧 `PROCESSING` → 新建；`PROCESSING` 同 body → `DUPLICATE_PROCESSING`；`DONE` 同 body → `DUPLICATE_DONE`；`FAILED` 同 body 且开关关 → `DUPLICATE_FAILED`；开关开 → 迁移 `PROCESSING`、`attempt += 1`、`RETRY_ALLOWED`；任意状态不同 body → `CONFLICT` 且保留首次记录；
    2. TTL `expires_at = first_seen + ttl_seconds`；`reserve()`/`purge()` 惰性清理；陈旧 `PROCESSING` 判定 `now - updated_at > stale_after_seconds`（默认 `task_timeout + 30`）；
    3. 容量：`OrderedDict` 按访问顺序；**优先淘汰非 `PROCESSING`**；全为活跃 `PROCESSING` 时不淘汰、允许临时超出并累加 `overflow`（在 `snapshot()` 暴露）；容量回落补淘汰；
    4. 所有读写在同一 `threading.Lock` 内；`reserve()` 是唯一「检查 + 写入」原子操作；
    5. `rollback()`：`NEW` → 删除；`RETRY_ALLOWED` → 恢复 `FAILED` 且 `attempt-1`；仅在记录属于本次占位时执行；
    6. 不持久化、不引入外部依赖、不写文件、不打日志。
  - 验收：
    1. `python -m py_compile backend/app/webhook/idempotency.py` 通过；
    2. 6 种 `ReservationState` 均可复现，`previous_state`、`attempt`、`error_code` 正确；
    3. 注入 `clock` 后 TTL 过期与陈旧 `PROCESSING` 行为可复现，无真实等待；
    4. 超容量时优先淘汰 `done/failed`，活跃 `PROCESSING` 不被淘汰且 `snapshot()` 含溢出计数；
    5. 多线程并发 `reserve()` 同一 `event_id` 仅一个 `NEW`（用 `threading.Barrier`，禁止 sleep 猜测）；
    6. 无文件写、无网络、无环境变量。
  - 回执：按 1.3 模板。

### 4.7 `backend/app/webhook/render.py`

- [ ] **新增评论渲染、截断与二次脱敏**
  - 完整路径：`backend/app/webhook/render.py`
  - 前置依赖：4.1
  - 输入：`CheckReport | None`、`NormalizedEvent`、`WebhookConfig`、执行状态、脱敏上下文
  - 输出：`CommentPayload`
  - 异常：`RenderError`（内部；空评论、统计不一致、marker 缺失）
  - 允许依赖：`re`、`typing`、`collections.abc`、`..core.rules.common.models`、`..core.rules.common.report`、`.models`、`.settings`、`.security`
  - 公开签名（与 design 2.4.1（11）逐字一致）：
    ```python
    class RenderError(Exception): ...

    def render_comment(
        report: "CheckReport | None",
        event: NormalizedEvent,
        config: WebhookConfig,
        *,
        executed: bool = True,
        status_reason: str | None = None,
        illegal_paths: "tuple[str, ...]" = (),
        absolute_roots: "tuple[str, ...]" = (),
        sensitive_values: "tuple[str, ...]" = (),
    ) -> CommentPayload: ...

    def render_groups(
        report: "CheckReport",
    ) -> "tuple[tuple[Finding, ...], tuple[Finding, ...]]": ...

    def truncate_comment(
        text: str, limit: int, marker: str
    ) -> "tuple[str, int, int, bool]": ...

    def apply_marker(text: str, marker: str) -> str: ...

    def redact_comment(
        text: str,
        secrets: "Sequence[str]" = (),
        absolute_roots: "Sequence[str]" = (),
    ) -> str: ...
    ```
  - 实现约束：
    1. 渲染结构与顺序按 design 2.4.1（11）固定模板：标题、仓库、PR/MR、检查状态、变更文件与来源、问题统计、跳过/降级/无法解析、必须修改、优化建议、未完成检查、降级说明、提示、marker；
    2. 分级排序：对 `report.files` 与组内 `findings` 做**两次顺序遍历**（先 `MUST_FIX`、后 `SUGGESTION`），保持原始相对顺序；不重排、不合并、不过滤、不补全；
    3. 统计头直接取 `report.summary` 七项，不重算；`INPUT_ERROR` 追加「输入存在错误，本次检查未完整执行」；
    4. 截断按 design 2.4.1（11）9 步：`limit = max_comment_chars`；固定区域预留 `min(2000, limit // 3)`；剩余预算必须修改最多 70%；最小单位是「一条完整问题块」；超条目输出「另有 N 条必须修改未展示」「另有 M 条优化建议未展示」；强制条目不得突破 `limit`；`len(markdown) <= limit`；marker 始终在末尾；
    5. 二次脱敏在拼装完成后调用 `redact_comment()`（规则与 `security.redact_text()` 一致，额外替换 `absolute_roots`、`sensitive_values`），替换发生在 marker 追加之前；
    6. 空结果区分严格按 design 表：`executed=True` + `issue_count=0` + `notify_on_clean=True` → 「本次检查未发现问题」；`notify_on_clean=False` → 不生成 payload；`executed=False`/异常/超时 → 「本次未执行检查：…」「检查未能完成：…」「检查超时：…」，**绝不输出「未发现问题」**；
    7. 脱敏后正文为空或仅剩 marker → `RenderError`，不发送空评论；
    8. 不得二次拼接引擎给出的原文（引擎已脱敏）。
  - 验收：
    1. `python -m py_compile backend/app/webhook/render.py` 通过；
    2. 渲染结果包含模板全部固定段，marker 在末尾，`char_count/byte_count/truncated` 与正文一致；
    3. 必须修改条目全部先于优化建议，组内相对顺序与 `report_to_dict()` 一致；
    4. 截断：任意 `limit` 下 `len(markdown) <= limit`；省略条目数正确；不截断半句；强制条目策略符合第 6/7 条；
    5. 假令牌、假密钥、`repo_root` 绝对路径全部替换为 `****`；
    6. 空结果/未执行/失败/超时五类文案可区分，未执行分支不含「未发现问题」；
    7. 未导入 `naming`、`code_scan`、`link_check`、`sensitive`、`engine`。
  - 回执：按 1.3 模板。

### 4.8 `backend/app/webhook/queue.py`

- [ ] **新增有界队列与 worker 编排**
  - 完整路径：`backend/app/webhook/queue.py`
  - 前置依赖：4.1
  - 输入：`capacity`、`concurrency`、`handler`、`task_timeout_seconds`、`clock`、`logger`
  - 输出：异步无返回；同步返回 `DeliveryRecord`
  - 异常：`QueueFullError`（429 `WEBHOOK_BUSY`）、`TaskTimeoutError`（内部，映射 `check_status="超时"`）
  - 允许依赖：`queue`（模块导入）、`threading`（模块导入）、`concurrent.futures`（模块导入）、`time`、`logging`、`typing`、`.models`
  - 公开签名（与 design 2.4.1（9）逐字一致）：
    ```python
    class QueueFullError(Exception):
        code: str = "WEBHOOK_BUSY"
        status_code: int = 429

    class TaskTimeoutError(Exception): ...

    class ReviewQueue:
        def __init__(
            self,
            capacity: int,
            concurrency: int,
            handler: "Callable[[ReviewJob], DeliveryRecord]",
            *,
            task_timeout_seconds: float,
            clock: "Callable[[], float] | None" = None,
            logger: "logging.Logger | None" = None,
        ) -> None: ...

        def start(self) -> None: ...
        def submit(self, job: ReviewJob) -> None: ...
        def run_now(self, job: ReviewJob, timeout: float | None = None) -> DeliveryRecord: ...
        def depth(self) -> int: ...
        def shutdown(self, timeout: float | None = None) -> None: ...
    ```
  - 实现约束：
    1. `_queue = queue.Queue(maxsize=capacity)`、`_semaphore = threading.BoundedSemaphore(concurrency)`、`_executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="repoguard-webhook")`、daemon worker 线程、`_stop = threading.Event()`；
    2. `submit()` 用 `put_nowait`；`queue.Full` → `QueueFullError`；不等待、不重试；
    3. worker 循环 `get(timeout=0.2)`；`queue.Empty` 且 `_stop` → 退出；任何异常在 `_execute` 内转为失败记录，worker 不退出；
    4. `_execute()`：`deadline = created_at + task_timeout_seconds`；已过 → 超时记录且不调用引擎；`semaphore.acquire(timeout=remaining)` 失败 → 超时记录；`executor.submit(handler, job)`；`future.result(timeout=remaining)`；`TimeoutError` → 超时记录（后台线程继续、结果丢弃）；
    5. `run_now()` 复用 `_execute()` 但不经队列，共享并发名额与执行器；无法在 `timeout` 内取得名额 → `QueueFullError`；
    6. `shutdown(timeout)`：置 `_stop` → `join` 每个 worker 至多 `timeout`（默认 `config.stop_timeout_seconds=10`）→ `executor.shutdown(wait=False, cancel_futures=False)`；已入队未执行任务由服务层补齐 `not_attempted`；
    7. 线程全部 daemon；不写文件、不联网、不打日志敏感信息。
  - 验收：
    1. `python -m py_compile backend/app/webhook/queue.py` 通过；
    2. 容量满时 `submit()` 抛 `QueueFullError`（`code/status_code` 正确）；
    3. `run_now()` 与 worker 共享并发上限，同一 `concurrency` 下不超发；
    4. 时限耗尽路径返回超时记录且不调用 handler（用 `clock` 注入，禁止真实等待 30 秒）；
    5. `shutdown()` 后 worker 全部退出、执行器释放，`depth()` 归零；
    6. 无 `from queue import ...`、`from threading import ...`、`from concurrent.futures import ...`。
  - 回执：按 1.3 模板。

### 4.9 `backend/app/webhook/service.py`

- [ ] **新增检查任务编排服务（唯一编排点）**
  - 完整路径：`backend/app/webhook/service.py`
  - 前置依赖：4.2、4.3、4.4、4.5、4.6、4.7、4.8
  - 输入：原始字节、头映射、`request_id`、`ReviewJob`
  - 输出：`IngestOutcome`、`DeliveryRecord`、`HealthSnapshot`
  - 异常：业务异常转为 `IngestOutcome`/`DeliveryRecord`；`EngineUnavailableError`（503）；未预期异常由路由兜底
  - 允许依赖：`pathlib`、`logging`、`json`、`time`、`typing`、`collections`、`.models`、`.settings`、`.signature`、`.parser`、`.security`、`.idempotency`、`.queue`、`.render`、`..core.rules.engine`、`..core.rules.common.models`、`..core.rules.common.report`、`..core.rules.common.config`（仅 `RuleConfig` 类型）、`..api.settings`、`..integrations.*`
  - 公开签名（与 design 2.4.1（10）逐字一致）：
    ```python
    class EngineUnavailableError(Exception):
        code: str = "ENGINE_UNAVAILABLE"
        status_code: int = 503

    def get_engine() -> "EngineRunner": ...

    class WebhookService:
        def __init__(
            self,
            config: WebhookConfig,
            web_settings: "WebSettings",
            *,
            runner: "EngineRunner | None" = None,
            adapter: "OpenApiAdapter | None" = None,
            registry: "IdempotencyRegistry | None" = None,
            queue: "ReviewQueue | None" = None,
            clock: "Callable[[], float] | None" = None,
            sleeper: "Callable[[float], None] | None" = None,
        ) -> None: ...

        def start(self) -> None: ...
        def shutdown(self, timeout: float | None = None) -> None: ...

        def handle_ingest(
            self, raw_body: bytes, headers: "Mapping[str, str]", request_id: str
        ) -> IngestOutcome: ...

        def handle_ingest_sync(
            self, raw_body: bytes, headers: "Mapping[str, str]", request_id: str
        ) -> IngestOutcome: ...

        def process_job(self, job: ReviewJob) -> DeliveryRecord: ...

        def health_snapshot(self) -> HealthSnapshot: ...

        def recent_records(self, limit: int = 50) -> "tuple[DeliveryRecord, ...]": ...
    ```
  - 实现约束：
    1. `handle_ingest()` 严格 10 步（design 2.4.1（10））：`enabled=false` → 503；密钥未配置 → 503；验签 → 401 分类；解析 → 400/422；归一化（类型/动作不满足 → 202 `ignored`、`skipped`、不占位）；仓库映射 → 403；`registry.reserve()`（`CONFLICT` 409、`DUPLICATE_*` 202 duplicate、`NEW`/`RETRY_ALLOWED` 继续）；清单可用性判定（可用 → 入队；`should_fetch_via_openapi` → `openapi` 入队；皆否 → `complete()` + 202 `degraded`/`not_attempted` + 后台降级说明）；`queue.submit()`（`QueueFullError` → `rollback` → 429）；成功 202 `accepted`/`queued`；
    2. `process_job()` 严格 9 步：`openapi` 来源先 `adapter.fetch_changed_files()`（`None`/`()` → 未执行 + 降级；成功 → 归一化 → `build_manifest()`）；`entry_count == 0` 或 `> max_changed_files` → 未执行不调引擎；**`run_check(job.manifest_text, job.repo_root, None)` 只出现一次**；异常 → `check_status="失败"`、`error_code="WEBHOOK_ENGINE_ERROR"`、按 `notify_on_failure` 回写、`registry.fail()`；报告状态映射（OK→正常、PARTIAL_DEGRADED→部分降级、INPUT_ERROR→输入错误）；`render_comment()`；模式分流（`disabled` → `skipped`、`reason="OpenAPI 未启用"`、`not_attempted`；`mock` → `MockOpenApiAdapter.publish_comment()` → `mock_delivered`；`live` → `ConfigurableOpenApiAdapter.publish_comment()`，成功 `delivered`，失败 `failed` + `error_code`）；`complete()`/`fail()`；写环形缓冲与单行 JSON 日志；
    3. 同步模式复用 `process_job()` 与同一执行器/并发闸门，不重复入队；状态码按 design 2.5.3（4）：200 completed / 202 degraded+not_attempted / 502 / 504 / 429，`disabled` → 200 `completed` + `not_attempted` + `skipped`；
    4. `notify_on_failure=false` 时未执行/失败不渲染不回写，`delivery_status="not_attempted"`；`notify_on_clean=false` 且 `issue_count=0` 时不回写 `skipped`；
    5. `health_snapshot()` 只读内存；引擎在构造时探测一次并缓存；`recent_delivery_failures` 统计 `failed`/`degraded`；`time = format_utc(utc_now())`；
    6. `get_engine()` 用相对导入 `from ..core.rules.engine import run_check`，不可用抛 `EngineUnavailableError`；
    7. 环形缓冲容量取 `record_buffer_size`，线程安全；
    8. 不写文件、不 clone、不执行被检查代码、不修改 payload。
  - 验收：
    1. `python -m py_compile backend/app/webhook/service.py` 通过；
    2. 10 步入站顺序与状态码矩阵（design 2.4.1（10）/spec 7.4）逐项可复现；
    3. `process_job()` 中 `run_check` 调用点唯一，正常/异常/降级/超时分支均 `calls == 1` 且 `config is None`；
    4. 未执行/失败/超时分支不输出「未发现问题」，`disabled` 分支零出站；
    5. `EngineUnavailableError` 映射 503；`QueueFullError` 映射 429 且占位回滚；
    6. 健康快照 13 字段完整、`dedup_size` 与 registry 一致、`queue_depth` 与 queue 一致；
    7. 日志单行 JSON、含 `request_id`/`event_id`/脱敏仓库标识、**不含**密钥/令牌/清单正文/评论正文/绝对路径；
    8. 未导入 `app.health.*`、`app.readme.*`、`app.shared.*`、`app.api.routes`、`app.api.app`，未导入四检查模块。
  - 回执：按 1.3 模板。

### 4.10 `backend/app/webhook/routes.py`

- [ ] **新增 Webhook HTTP 路由与错误映射**
  - 完整路径：`backend/app/webhook/routes.py`
  - 前置依赖：4.9
  - 输入：`WebhookService`、`WebhookConfig`、`fastapi.Request`
  - 输出：`fastapi.APIRouter`、`starlette.responses.JSONResponse`
  - 异常：业务异常由处理器统一映射；未预期异常 → 500 `WEBHOOK_INTERNAL_ERROR`
  - 允许依赖：`fastapi`（模块导入）、`starlette.responses`（模块导入）、`starlette.exceptions`（模块导入）、`json`、`logging`、`time`、`uuid`、`typing`、`.models`、`.service`、`.settings`
  - 公开签名（与 design 2.4.1（12）逐字一致）：
    ```python
    def build_router(service: WebhookService, config: WebhookConfig) -> "fastapi.APIRouter": ...

    def install_middleware(app: "fastapi.FastAPI", config: WebhookConfig) -> None: ...

    def install_exception_handlers(app: "fastapi.FastAPI") -> None: ...

    def error_response(
        request: "fastapi.Request",
        code: str,
        status_code: int,
        message: str,
        detail: str | None = None,
    ) -> "starlette.responses.JSONResponse": ...
    ```
  - 实现约束：
    1. `POST {config.path}` 固定 8 步：仅 POST（其他方法 405）→ `Content-Type` 首段必须 `application/json`（否则 415，不读体）→ `enabled=false` 503（不读体）→ `Content-Length` 预检 > 上限 413（不读体）→ `async for chunk in request.stream()` 累计超限立即停止并 413（**禁止** `await request.body()` 无界读取）→ `secret_configured()` 假 503（不读体）→ `service.handle_ingest()` 或 `handle_ingest_sync()` → 返回 `IngestOutcome.body` + 状态码 + `Content-Type: application/json; charset=utf-8` + `Cache-Control: no-store` + `X-Request-ID`；
    2. `GET /healthz` 只调用 `health_snapshot()`；`ok` → 200，否则 503；`Cache-Control: no-store`；不执行引擎、不扫文件、不出站；
    3. 中间件：`request_id = uuid.uuid4().hex`；记录开始时间；响应后单行 JSON 日志；设置 `X-Request-ID`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`；日志异常不影响响应；
    4. 异常处理器按 design 2.4.1（12）表：`WebhookError` 用其 `code/status_code/message/detail`；404 → `NOT_FOUND`；405 → `METHOD_NOT_ALLOWED`；其他 → `WEBHOOK_INTERNAL_ERROR` 且不泄露堆栈；
    5. 错误响应体固定结构 `{"status": "rejected", "error": {...}, "request_id": ...}`；成功响应体固定 6 字段；
    6. 401/403 响应结构一致，不泄露仓库存在性、不泄露期望签名/密钥长度/头原文；
    7. 不设路由前缀；`/webhook` 与 `/healthz` 为绝对路径。
  - 验收：
    1. `python -m py_compile backend/app/webhook/routes.py` 通过；
    2. 15 个错误码（400/401×4/403×2/404/405/409/413/415/422/429/500/502/503×3/504）均可由对应输入触发，状态码与码值一致；
    3. 415、503（disabled/密钥未配置）、413（`Content-Length` 预检）在读取请求体前拒绝；
    4. 分块读取超限返回 413 且不进入 service；
    5. 成功响应 6 字段、`Cache-Control: no-store`、`X-Request-ID` 存在；`/healthz` 13 字段；
    6. 异常处理器不返回堆栈、不返回英文内部信息；
    7. 文件内无 `from fastapi import ...`、`from starlette... import ...`、`from app...`。
  - 回执：按 1.3 模板。

### 4.11 `backend/app/webhook/app.py`

- [ ] **新增独立 Webhook 应用工厂**
  - 完整路径：`backend/app/webhook/app.py`
  - 前置依赖：4.10
  - 输入：`config`、可注入 `service/runner/adapter/clock/sleeper/web_settings`
  - 输出：`fastapi.FastAPI`、模块级 `app`
  - 异常：构造失败向上抛；配置非法不抛（`settings` 回退）；引擎不可用不阻止构造（健康降级）
  - 允许依赖：`fastapi`（模块导入）、`contextlib`、`logging`、`typing`、`.service`、`.routes`、`.settings`、`.models`、`..api.settings`、`..integrations.*`
  - 公开签名（与 design 2.4.1（13）逐字一致）：
    ```python
    SERVICE_NAME: str = "repoguard-webhook"
    SERVICE_VERSION: str = "1.0.0"

    def create_webhook_app(
        config: WebhookConfig | None = None,
        *,
        service: WebhookService | None = None,
        web_settings: "WebSettings | None" = None,
        runner: "EngineRunner | None" = None,
        adapter: "OpenApiAdapter | None" = None,
        clock: "Callable[[], float] | None" = None,
        sleeper: "Callable[[float], None] | None" = None,
    ) -> "fastapi.FastAPI": ...

    app = create_webhook_app()
    ```
  - 实现约束：
    1. 装配顺序 8 步：`normalize_config(config or load_webhook_config())` → `web_settings or load_settings_from_env()`（只读复用阶段 2 白名单）→ `WebhookService(...)` → `fastapi.FastAPI(title="RepoGuard Webhook", version=SERVICE_VERSION, lifespan=...)` → 写入 `application.state.webhook_config`/`webhook_service`/`request_started` → `install_middleware()`/`install_exception_handlers()` → `include_router(build_router(svc, effective))`（无前缀）→ lifespan startup `svc.start()`、shutdown `svc.shutdown(stop_timeout_seconds)`；
    2. 模块级 `app = create_webhook_app()` **不得启动 worker 线程**（线程只在 lifespan startup 启动）；
    3. `disabled` 模式**不构造任何出站适配器**；`mock` 构造 `MockOpenApiAdapter`；`live` 仅在 `validate_profile()` 全部通过时构造 `ConfigurableOpenApiAdapter`，缺失时保留 `None` 并健康降级；
    4. 启动日志中文单行，字段按 design 2.4.1（13）：监听地址端口、路径、签名算法、OpenAPI 模式、允许仓库数、队列容量、签名密钥是否配置、令牌是否配置；**不含**密钥/令牌/绝对路径/模板原文；
    5. **禁止**默认 `0.0.0.0`、禁止把 Webhook 路由注册到阶段 2 应用、禁止 `--reload`。
  - 验收：
    1. `python -m py_compile backend/app/webhook/app.py` 通过；
    2. `create_webhook_app()` 返回独立应用，`app.routes` 含配置路径与 `/healthz`；
    3. `import app.webhook.app` 不产生线程、不产生网络、不监听端口；`app` 对象构造成功；
    4. 注入 `service` 时以注入实例为准，可完全替换；
    5. `disabled` 下无 `ConfigurableOpenApiAdapter`/`MockOpenApiAdapter` 实例；
    6. 启动日志不含敏感值与绝对路径；
    7. 文件内无 `from fastapi import ...`、`from app...`。
  - 回执：按 1.3 模板。

### 4.12 `backend/app/webhook/__init__.py` 与 `__main__.py`

- [ ] **（12-A）新增包导出**
  - 完整路径：`backend/app/webhook/__init__.py`
  - 前置依赖：4.11
  - 输入：无
  - 输出：`__all__` 元组
  - 异常：仅标准 `ImportError`，不兜底吞异常
  - 允许依赖：`.app`、`.settings`
  - 公开签名（与 design 2.4.1（1）逐字一致）：
    ```python
    __all__: tuple[str, ...] = (
        "create_webhook_app",
        "app",
        "WebhookConfig",
        "WebhookService",
        "load_webhook_config",
    )
    ```
  - 验收：
    1. `python -m py_compile backend/app/webhook/__init__.py` 通过；
    2. `python -c "import app.webhook"` 成功且**不启动 worker 线程**、不监听端口、不产生网络；
    3. `__all__` 与签名一致；无 `from app...`。
  - 回执：按 1.3 模板。

- [ ] **（12-B）新增独立启动入口**
  - 完整路径：`backend/app/webhook/__main__.py`
  - 前置依赖：4.12（A）
  - 输入：`argv: Sequence[str] | None = None`（保留形参，不解析命令行选项）
  - 输出：`int` 退出码：`0` 正常返回（仅在测试替换启动器时），`1` 端口占用/启动失败
  - 异常：捕获 `OSError` → 中文日志 → 返回 `1`；配置非法不抛异常（`settings` 回退并告警）
  - 允许依赖：`sys`、`os`、`logging`、`uvicorn`（模块导入）、`.app`、`.settings`
  - 公开签名（与 design 2.4.1（2）逐字一致）：
    ```python
    def main(argv: "Sequence[str] | None" = None) -> int: ...

    if __name__ == "__main__":
        raise SystemExit(main())
    ```
  - 实现约束：
    1. 启动序列 5 步：`load_webhook_config()` → `create_webhook_app(config)` → `host == "0.0.0.0"` 输出中文安全警告「已对外暴露，必须由反向代理提供 TLS 与访问控制」→ `uvicorn.run(application, host=config.host, port=config.port, log_level=config.log_level.lower())` → `OSError` 日志「Webhook 监听失败：端口可能已被占用，请更换端口或释放占用」并返回 `1`；
    2. **禁止** `--reload`、自动改端口、默认 `0.0.0.0`、输出密钥/令牌/绝对路径；
    3. 默认监听必须为 `127.0.0.1:8010`。
  - 验收：
    1. `python -m py_compile backend/app/webhook/__main__.py` 通过；
    2. `python -m app.webhook` 在 `backend/` 下可启动，监听 `127.0.0.1:8010`（人工启动验证，**不在测试内执行**）；
    3. 用替身替换 `uvicorn.run` 后 `main()` 返回 0；`OSError` 分支返回 1 且输出中文提示；
    4. `host="0.0.0.0"` 时输出安全警告；
    5. 进程日志不含敏感值；
    6. 与阶段 2 `python -m app.api.app`（或既有启动方式）互不影响，可同时运行。
  - 回执：按 1.3 模板。

---

## 5. 测试基础设施（`backend/tests/webhook_helpers.py` 与 4 个 fixture）

> 测试总则（适用于第 5～7 节全部任务）：
> 1. 统一 `unittest`：`unittest.TestCase`、`unittest.skipUnless`、`unittest.mock.patch`；运行器固定 `python -m unittest discover -s tests -v`；
> 2. 禁止引入其他测试运行器、其夹具装饰器、其断言风格；发现即门禁失败；
> 3. 入站只允许 `httpx.AsyncClient(transport=httpx.ASGITransport(app=...))` 驱动，封装在 `WebhookASGIClient` 内；禁止使用 Web 框架内置的同步测试客户端；
> 4. 出站只允许 `httpx.MockTransport`、`MockOpenApiAdapter`（内存）、`MockOpenApiService`（`httpx.ASGITransport`）；
> 5. 禁止 `uvicorn.run`、禁止绑定端口、禁止公网 DNS、禁止真实等待（`clock`/`sleeper` 注入）；
> 6. 每个用例使用 `tempfile.TemporaryDirectory()`，禁止依赖 `demo-repo` 真实内容；密钥/令牌为随机假值，仅存在于用例作用域；
> 7. 并发用例使用 `threading.Barrier`/`Event`，禁止 `sleep` 猜测；
> 8. 每个测试文件独立可跑：`python -m unittest tests.<module> -v`。

### 5.1 `backend/tests/webhook_helpers.py`

- [ ] **新增测试辅助模块**
  - 完整路径：`backend/tests/webhook_helpers.py`
  - 前置依赖：4.12
  - 输入：密钥、时间戳、原始字节、事件类型、事件标识、payload 构造参数、应用
  - 输出：签名值、头字典、payload 字典、可控时钟、同步 ASGI 客户端
  - 异常：参数非法 `ValueError`；客户端 `close()` 不抛异常
  - 允许依赖：标准库、`httpx`（模块导入）、`fastapi`（仅类型标注）、`app.webhook.*`
  - 公开签名（与 design 2.4.3 逐字一致）：
    ```python
    def make_signature(secret: str, timestamp: str, raw_body: bytes) -> str: ...
    def make_headers(
        secret: str,
        raw_body: bytes,
        event_type: str = "pr.created",
        event_id: str = "evt-001",
        *,
        timestamp: str | None = None,
        signature_prefix: str = "sha256=",
        delivery_id: str | None = None,
    ) -> "dict[str, str]": ...
    def make_payload(
        *,
        repo: str = "demo-repo",
        pr_number: int = 12,
        base_sha: str = "a" * 40,
        head_sha: str = "b" * 40,
        changed_files: "list[str] | None" = None,
        added_files: "list[str] | None" = None,
        modified_files: "list[str] | None" = None,
        removed_files: "list[str] | None" = None,
        action: str = "opened",
    ) -> "dict[str, object]": ...
    class FrozenClock:
        def __init__(self, seconds: float) -> None: ...
        def __call__(self) -> float: ...
        def advance(self, seconds: float) -> None: ...
    class WebhookASGIClient:
        def __init__(self, app: "fastapi.FastAPI", timeout: float = 10.0) -> None: ...
        def get(self, path: str, **kwargs: object) -> "httpx.Response": ...
        def post(self, path: str, **kwargs: object) -> "httpx.Response": ...
        def close(self) -> None: ...
    ```
  - 实现约束：
    1. `make_signature()` 必须与生产 `build_signature()` 使用同一算法口径（`timestamp + "." + body`，HMAC-SHA256，hex）；
    2. `make_headers()` 默认生成配置声明的四类头；`signature_prefix=""` 时生成裸 hex；`timestamp=None` 时取当前秒；
    3. `make_payload()` 只生成 `changed_files` 与 `added/modified/removed_files` 中传入的字段，不生成空占位；
    4. `WebhookASGIClient` 内部使用 `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`，对外暴露同步 `get/post`；**不得使用同步测试客户端**；
    5. 提供无网络上下文（patch `socket.socket` 与 `socket.create_connection` 抛 `AssertionError`），供用例复用；
    6. 辅助模块不包含 `TestCase` 子类，不被 `unittest discover` 收集为用例。
  - 验收：
    1. `python -m py_compile backend/tests/webhook_helpers.py` 通过；
    2. `make_signature()` 产出的签名能被生产 `verify_signature()` 接受；
    3. `WebhookASGIClient` 可对 `create_webhook_app()` 发起 `post`/`get` 并返回 `httpx.Response`；
    4. 辅助模块无 `TestCase`、无真实 port、无 `uvicorn`；
    5. 全部密钥/令牌为参数传入，无硬编码真实值。
  - 回执：按 1.3 模板。

### 5.2 4 个 fixture 样例

- [ ] **新增 4 个事件样例 JSON**
  - 完整路径与内容约束：
    1. `backend/tests/fixtures/webhook_pr_created.json`：PR 创建样例，含 `changed_files` 形式；字段可被默认 `field_map` 命中（事件标识、仓库、PR 编号、base/head sha、action）；
    2. `backend/tests/fixtures/webhook_pr_updated.json`：PR 更新样例，含 `added_files`/`modified_files`/`removed_files` 形式；
    3. `backend/tests/fixtures/webhook_mr_created.json`：MR 创建样例，含 `project.path_with_namespace`、`object_attributes`（PR 编号、sha、action）映射；
    4. `backend/tests/fixtures/webhook_changed_files_missing.json`：缺失变更清单样例，**不含**任何变更文件字段，用于触发 `openapi`/`none` 降级路径。
  - 前置依赖：5.1
  - 输入：无（静态样例）
  - 输出：4 个 UTF-8 JSON 文件
  - 异常：无
  - 验收：
    1. 4 个文件均为合法 JSON 对象（顶层为 object）；
    2. **不含**真实密钥、真实令牌、真实仓库全名、真实用户名、绝对路径；仓库名统一 `demo-repo` 或 `acme/lab-01` 类假值；
    3. PR created 能被 `parse_event()` + `normalize_event()` 解析为 `changed_files_source="payload"`；
    4. PR updated 能解析为 `payload_lists` 且含 `A`/`M`/`D` 三种状态；
    5. MR created 能通过默认字段映射解析出 PR 编号与仓库标识；
    6. missing 样例解析后 `changed_files_available=False`、来源为 `openapi` 或 `none`；
    7. 不得覆盖既有 `backend/tests/fixtures/sample_changes.txt`。
  - 回执：按 1.3 模板。

---

## 6. 测试用例文件（8 个，逐文件串行）

### 6.1 `backend/tests/test_webhook_signature.py`（W01–W12）

- [ ] **覆盖验签、时间戳、重放窗口与密钥轮换**
  - 完整路径：`backend/tests/test_webhook_signature.py`
  - 前置依赖：5.1、5.2、4.12
  - 覆盖用例（编号与 spec 9.6.2 一致）：
    - W01 `test_signature_ok`、W02 `test_signature_missing`、W03 `test_signature_invalid`、W04 `test_signature_body_tampered`、W05 `test_signature_prefix_optional`、W06 `test_signature_wrong_length`、W07 `test_timestamp_missing`、W08 `test_timestamp_expired`、W09 `test_timestamp_future`、W10 `test_timestamp_millis`、W11 `test_secret_unconfigured`、W12 `test_secret_rotation_previous`
  - 驱动方式：
    - W01/W02/W11：`WebhookASGIClient` + `httpx.ASGITransport`（状态码与「不读体」断言）；
    - W03～W10、W12：直接调用 `verify_signature()` / `parse_timestamp()` / `build_signature()`（`now` 注入，禁止真实时间依赖）；
    - 全程 `patch("socket.socket", side_effect=AssertionError)`（W11/W02 用可计数 async generator 证明未消费 `yield`）。
  - 验收：
    1. 12 个用例名与矩阵一致，可单独 `python -m unittest tests.test_webhook_signature -v` 运行；
    2. W02 断言 401 `WEBHOOK_SIGNATURE_MISSING` 且请求体 `yield` 次数为 0；
    3. W11 断言 503 `WEBHOOK_SECRET_NOT_CONFIGURED` 且请求体未消费；
    4. W10 断言 13 位毫秒被识别、`timestamp_unit=="milliseconds"`；
    5. W12 断言通过且 `used_previous=True`，响应文案不区分密钥版本；
    6. 无真实等待、无端口、无公网、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.2 `backend/tests/test_webhook_parser.py`（W13–W28）

- [ ] **覆盖解析、字段映射、清单来源与路径归一化**
  - 完整路径：`backend/tests/test_webhook_parser.py`
  - 前置依赖：5.1、5.2、4.12
  - 覆盖用例：W13 `test_json_invalid`、W14 `test_content_type_rejected`、W15 `test_payload_too_large_content_length`、W16 `test_payload_too_large_chunked`、W17 `test_event_type_allowed`、W18 `test_event_type_ignored`、W19 `test_event_invalid_missing_pr`、W20 `test_field_map_custom`、W21 `test_event_id_fallback_delivery_header`、W22 `test_event_id_fallback_content_hash`、W23 `test_changed_files_from_payload`、W24 `test_changed_files_from_lists`、W25 `test_changed_files_from_openapi`、W26 `test_changed_files_unavailable`、W27 `test_illegal_paths_filtered`、W28 `test_manifest_construction`
  - 驱动方式：
    - W14/W15/W16：按 design 2.4.3 编号归属放在本文件，但必须用 `WebhookASGIClient` + `httpx.ASGITransport` 驱动传输层断言（不得新增 parser 私有入口伪造）；
    - W18：同样用 ASGI 客户端断言 202 `ignored`、无检查、无回写；
    - W13/W17/W19～W28：直接调用 `decode_json_object()`、`parse_event()`、`normalize_event()`、`extract_changed_files()`、`normalize_changed_path()`、`build_manifest()`、`should_fetch_via_openapi()`；
    - W28 使用 5,000 条边界（配置 `max_changed_files` 注入小值验证上限判定，不真的构造 5,000 条耗时数据）。
  - 验收：
    1. 16 个用例名与矩阵一致，可单独运行；
    2. W14 断言 415 且请求体未消费；W15 断言 413 且不读体；W16 断言分块超限 413；
    3. W18 断言 202 `ignored`、`action="skipped"`、检查与回写均未发生；
    4. W20 自定义 `field_map` 生效，默认路径被覆盖；
    5. W21/W22 断言 `event_id_source` 分别为 `delivery_header`/`content_hash`，且 W22 两次哈希一致、为 64 位 hex；
    6. W23/W24/W25/W26 断言来源枚举与「是否调用 OpenAPI」判定正确；
    7. W27 断言 `..`、绝对路径、盘符、UNC 全部剔除且 `illegal_paths` 计数正确；
    8. W28 断言每行格式 `状态 + 空格 + 路径`、含空格路径原样、`entry_count == 行数`；
    9. 无端口、无公网、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.3 `backend/tests/test_webhook_service.py`（W29–W38）

- [ ] **覆盖仓库映射、引擎调用次数、异常/降级/超时与队列满**
  - 完整路径：`backend/tests/test_webhook_service.py`
  - 前置依赖：6.2、4.12
  - 覆盖用例：W29 `test_repo_mapping_allowed`、W30 `test_repo_forbidden`、W31 `test_no_remote_clone`、W32 `test_run_check_called_once`、W33 `test_no_module_imports`、W34 `test_engine_degraded_passthrough`、W35 `test_engine_exception`、W36 `test_engine_input_error`、W37 `test_task_timeout`、W38 `test_queue_full`
  - 驱动方式：
    - W29/W30：直接调用 `resolve_event_repo()` + `tempfile.TemporaryDirectory()` 构造白名单根；
    - W31/W33：AST/文本静态扫描新增 18 个产品文件（禁止 `clone`、`subprocess`、`os.system`；禁止四检查模块导入）；
    - W32/W34/W35/W36/W37：直接调用 `WebhookService.process_job()`，注入计数 `runner` 与 `MockOpenApiAdapter`（InMemory）；
    - W37 用 `FrozenClock` 使预算预先耗尽（禁止真实等待 30 秒）；
    - W38 用 `WebhookASGIClient`（capacity=1，先占满队列；用 `threading.Event` 控制 handler 阻塞）断言 429 与占位回滚；
    - 全程 socket 补丁（除 W38 的 ASGI 调用，也不建 socket）。
  - 验收：
    1. 10 个用例名与矩阵一致，可单独运行；
    2. W32 断言 `calls == 1` 且最后一次调用 `config is None`；异常分支同样 `calls == 1`；
    3. W34 评论保留 `degraded_modules` 与中文原因；W35 记录 `failed` 且正文不含「未发现问题」；W36 保留「输入错误」；
    4. W37 记录 `check_status="超时"`、`error_code` 为超时码，不调用引擎；
    5. W38 断言 429 `WEBHOOK_BUSY` 且 registry 中该事件已回滚（可再次 `reserve()` 得到 `NEW`）；
    6. W30 断言 403 且未触发任何文件系统探测（用 `unittest.mock.patch` 计数）；
    7. W31/W33 扫描结果为 0 命中；
    8. 无真实网络、无端口、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.4 `backend/tests/test_webhook_idempotency.py`（W39–W44）

- [ ] **覆盖重复、并发、冲突、TTL、容量与失败重放**
  - 完整路径：`backend/tests/test_webhook_idempotency.py`
  - 前置依赖：6.3、4.12
  - 覆盖用例：W39 `test_duplicate_event`、W40 `test_concurrent_duplicate`、W41 `test_event_conflict`、W42 `test_idempotency_ttl_expired`、W43 `test_idempotency_capacity_eviction`、W44 `test_retry_failed_disabled_by_default`
  - 驱动方式：
    - W39/W41：`WebhookASGIClient` + 注入 `MockOpenApiAdapter` 与计数 `runner`（断言 202 duplicate / 409 与不重复回评）；
    - W40：`threading.Barrier` + 多线程直接调用 `IdempotencyRegistry.reserve()`（禁止 sleep）；
    - W42/W43/W44：直接调用 registry，注入 `FrozenClock`，使用纯 `unittest` 断言；
    - 全程无真实网络、无端口。
  - 验收：
    1. 6 个用例名与矩阵一致，可单独运行；
    2. W39 断言 202、`duplicate=true`、`comments` 长度不增、`runner` 调用次数不增；
    3. W40 断言 N 线程并发仅 1 个 `NEW`，其余为 `DUPLICATE_PROCESSING`；
    4. W41 断言 409 `WEBHOOK_EVENT_CONFLICT` 且首次记录保留（body 哈希与 state 不变）；
    5. W42 TTL 过期后同一事件可再次 `NEW`；
    6. W43 断言超容量淘汰计数正确、活跃 `PROCESSING` 不被淘汰、`snapshot()` 含溢出计数；
    7. W44 默认 `DUPLICATE_FAILED`（不重放）；显式开启后 `RETRY_ALLOWED` 且 `attempt` 递增；
    8. 无真实等待、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.5 `backend/tests/test_webhook_comment.py`（W45–W49）

- [ ] **覆盖评论结构、截断、marker、脱敏与空结果区分**
  - 完整路径：`backend/tests/test_webhook_comment.py`
  - 前置依赖：6.4、4.12
  - 覆盖用例：W45 `test_comment_structure`、W46 `test_comment_truncation`、W47 `test_comment_marker`、W48 `test_comment_redaction`、W49 `test_comment_empty_vs_not_executed`
  - 驱动方式：直接调用 `render_comment()`、`render_groups()`、`truncate_comment()`、`apply_marker()`、`redact_comment()`；`CheckReport` 通过阶段 1 的 `run_check()` 在临时仓库上生成（只读，单次），或按不可变模型手工构造；**不启动应用、不建端口**。
  - 验收：
    1. 5 个用例名与矩阵一致，可单独运行；
    2. W45 断言必须修改全部在优化建议之前、统计头与 `report.summary` 七项一致；
    3. W46 断言任意 `limit` 下 `len(markdown) <= limit`、省略计数正确、不截断半句、marker 保留；
    4. W47 断言 marker 出现在正文末尾（允许末尾一个换行）；
    5. W48 断言假令牌、假密钥、绝对路径替换为 `****`，且不保留长度信息；
    6. W49 断言 `executed=True` 且 `issue_count=0` 时含「本次检查未发现问题」；`executed=False`/异常/超时时**不含**该文案且含对应中文原因；
    7. `notify_on_clean=False` 时不生成 payload；
    8. 无网络、无端口、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.6 `backend/tests/test_webhook_openapi.py`（W50–W59）

- [ ] **覆盖出站配置化、超时、重试、失败不伪装与主机白名单**
  - 完整路径：`backend/tests/test_webhook_openapi.py`
  - 前置依赖：6.5、4.12
  - 覆盖用例：W50 `test_openapi_disabled_no_request`、W51 `test_openapi_mock_delivered`、W52 `test_openapi_timeout_retry`、W53 `test_openapi_429_retry`、W54 `test_openapi_5xx_retry_then_fail`、W55 `test_openapi_401_no_retry`、W56 `test_openapi_404_no_retry`、W57 `test_openapi_live_incomplete`、W58 `test_openapi_host_forbidden`、W59 `test_openapi_no_redirect`
  - 驱动方式：
    - W50/W51：`WebhookASGIClient` + `MockOpenApiAdapter`（InMemory），断言 `skipped` / `mock_delivered`；
    - W52～W56、W58、W59：`httpx.MockTransport` + `HttpxHttpClient` + `ConfigurableOpenApiAdapter`，注入 `sleeper` 替身记录退避；
    - W57：`validate_profile()` 直接断言 + `WebhookASGIClient` 断言 `/healthz` 503 与同步 POST 503 `OPENAPI_NOT_CONFIGURED`；
    - W58 断言 MockTransport handler 调用次数为 0（URL 越界时不得发请求）；
    - W59 断言 3xx 不重试、`attempts=1`、`OPENAPI_REDIRECT_FORBIDDEN`；
    - 全程 socket 补丁。
  - 验收：
    1. 10 个用例名与矩阵一致，可单独运行；
    2. W50 断言零出站（adapter 未构造或未调用）且 `delivery_status="skipped"`、`reason` 为中文；
    3. W52 断言 `attempts=3`、`error_code=="OPENAPI_TIMEOUT"`、`success is False`、sleep 调用 2 次且退避在 `base*2**(n-1)` 的 ±20% 内；
    4. W53 断言 429→成功、`attempts=2`、`retried=True`；
    5. W54 断言重试耗尽 `OPENAPI_UNAVAILABLE`、`success is False`（不得伪装 delivered）；
    6. W55/W56 断言 `attempts=1` 且 handler 调用 1 次；
    7. W57 断言缺失字段名列表出现在错误说明中、健康 `degraded`、**未回退到 `mock`/`disabled`**；
    8. W58 断言 `OPENAPI_HOST_FORBIDDEN`、无请求；
    9. W59 断言 3xx → `OPENAPI_REDIRECT_FORBIDDEN`；
    10. 无真实网络、无端口、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.7 `backend/tests/test_webhook_api.py`（W60–W65）

- [ ] **覆盖 ASGI 集成、健康、路由隔离与 CLI 回归**
  - 完整路径：`backend/tests/test_webhook_api.py`
  - 前置依赖：6.6、4.12
  - 覆盖用例：W60 `test_health_ok`、W61 `test_health_degraded`、W62 `test_health_method_not_allowed`、W63 `test_phase2_routes_unchanged`、W64 `test_cli_regression`、W65 `test_no_network_outside_mock`
  - 驱动方式：
    - W60/W61/W62/W65：`WebhookASGIClient` + `httpx.ASGITransport`；
    - W63：直接导入阶段 2 应用（测试代码允许绝对导入），断言路径集合；
    - W64：`subprocess` 调用 `sys.executable -m app.core.rules.engine --format json`（不启动端口、不联网），断言退出码与 JSON 键集合；
    - W65：`patch("socket.socket")` + `patch("socket.create_connection")` 包裹 disabled 与 mock 两条链路。
  - 验收：
    1. 6 个用例名与矩阵一致，可单独运行；
    2. W60 断言 200、13 个字段齐全、`service=="repoguard-webhook"`、`version=="1.0.0"`、`Cache-Control: no-store`；
    3. W61 至少覆盖三种降级：密钥空、引擎不可用、live 缺配置，均 503 `degraded`；
    4. W62 断言 `GET` 以外的 `/healthz` 方法 405 `METHOD_NOT_ALLOWED`；同时覆盖 `POST /webhook` 接受外的方法 405；
    5. W63 断言阶段 2 路由集合含 `/`、`/api/health`、`/api/review`，**不含** `/webhook`、`/healthz`；路由集合以测试内常量断言，不读取外部快照文件；
    6. W64 断言 CLI 退出码 0、`--format json` 键集合与阶段 1 基线一致；**12 passed 的计数由任务 29.3 单独执行 `tests.test_cli` 保证**，不在本用例内嵌套跑测试套件；
    7. W65 断言 disabled 与 mock 链路均无真实 socket；
    8. 无端口、无公网、无其他测试运行器。
  - 回执：按 1.3 模板。

### 6.8 `backend/tests/test_webhook_e2e_offline.py`（W66 + 可选回环）

- [ ] **（8-A）覆盖离线端到端链路**
  - 完整路径：`backend/tests/test_webhook_e2e_offline.py`
  - 前置依赖：6.7、4.12
  - 覆盖用例：W66 `test_offline_e2e`
  - 驱动方式与流程（与 design 2.5.7（3）一致）：
    1. `tempfile.TemporaryDirectory()` 构造临时仓库（含 2～3 个 `.py` 文件与 1 个清单内文件）；
    2. `make_payload()` + `make_signature()` + `make_headers()` 生成合法事件；
    3. `WebhookASGIClient.post("/webhook", content=raw, headers=headers)` → 断言 202 `accepted`；
    4. 显式 `service.start()` 时由 worker 消费；或使用 `handle_ingest_sync()` + `process_job()` 路径（二选一，需在用例注释中说明）；
    5. `run_check()` 对临时仓库真实执行一次；
    6. `render_comment()` → `MockOpenApiAdapter.publish_comment()`；
    7. 断言 `comments[0].markdown` 含 marker、统计与报告一致；
    8. 断言 `DeliveryRecord.delivery_status == "mock_delivered"`；
    9. 断言计数 `runner` 调用次数为 1、`config is None`；
    10. 全程 `patch("socket.socket", side_effect=AssertionError)`。
  - 验收：
    1. W66 用例名与矩阵一致，可单独运行；
    2. 链路 202 → 队列/同步 → 检查 → 渲染 → mock 回写 → 记录完整，无跳步；
    3. marker 在正文末尾；评论统计与 `report.summary` 一致；
    4. `run_check` 恰好 1 次；`delivery_status=="mock_delivered"`；
    5. 临时目录清理，无仓库写入；
    6. 无真实网络、无端口、无其他测试运行器。
  - 回执：按 1.3 模板。

- [ ] **（8-B）可选回环 E2E（默认跳过，不属于门禁）**
  - 完整路径：同上文件内独立用例 `test_loopback_e2e_optional`
  - 前置依赖：6.8（A）
  - 开关：仅当环境变量 `REPOGUARD_WEBHOOK_E2E_LOOPBACK == "1"` 时运行；否则必须 `unittest.skipUnless` 跳过，`reason` 为「回环 E2E 需显式开启 REPOGUARD_WEBHOOK_E2E_LOOPBACK=1」
  - 驱动方式：`127.0.0.1:0`（操作系统分配随机端口）启动本地回环服务线程，超时 5 秒；**禁止** `0.0.0.0`、固定端口、公网 DNS
  - 验收：
    1. 未设置开关时显示 skipped，且 skipped 计数与基线口径分开记录（不纳入 3 条既有 skipped）；
    2. 设置开关后可运行并通过；
    3. 该用例失败**不得阻塞主流程**，但必须在交付报告中如实记录；
    4. 该用例是唯一允许绑定端口的测试，且仅 `127.0.0.1`。
  - 回执：按 1.3 模板，注明 skipped 或 passed 与开关状态。

---

## 7. 审计、回归与交付

### 7.1 导入方向与写操作审计

- [ ] **审计新增包的导入方向**
  - 前置依赖：第 6 节全部通过
  - 输入：18 个新增产品文件
  - 命令思路：用 AST 遍历 `ast.ImportFrom` / `ast.Import`，逐文件输出违规项（可在执行记录中用一次性脚本完成，**不得把脚本提交进仓库**）
  - 审计规则（与 spec 10.5、design 2.4 一致）：
    1. 绝对 `from X import ...` 的根只允许：`__future__`、`argparse`、`ast`、`collections`、`dataclasses`、`enum`、`ipaddress`、`json`、`math`、`os`、`pathlib`、`re`、`sys`、`time`、`traceback`、`types`、`typing`、`unittest`；
    2. 允许的模块导入形式：`import fastapi`、`import httpx`、`import uvicorn`、`import hmac`、`import hashlib`、`import threading`、`import queue`、`import concurrent.futures`、`import urllib.parse`、`import starlette.responses`、`import starlette.exceptions`、`import time`、`import json`、`import os`、`import re`、`import sys`、`import logging`、`import uuid`、`import contextlib`、`import collections`、`import dataclasses`、`import enum`、`import pathlib`、`import datetime`、`import ipaddress`、`import random`；
    3. **禁止**：`from fastapi import ...`、`from httpx import ...`、`from starlette... import ...`、`from uvicorn import ...`、`from app...`、`from hmac import ...`、`from hashlib import ...`、`from threading import ...`、`from queue import ...`、`from concurrent.futures import ...`、`from urllib.parse import ...`、`from datetime import ...`；
    4. 相对导入首段不得为 `naming`、`code_scan`、`link_check`、`sensitive`、`engine`；
    5. 禁止导入 `app.health.*`、`app.readme.*`、`app.shared.*`、`app.api.routes`、`app.api.app`；
    6. 允许的相对导入：`..core.rules.engine`、`..core.rules.common.models`、`..core.rules.common.report`、`..core.rules.common.config`、`..api.settings`、`..api.security`、`..integrations.*`、`.models`、`.settings`、`.signature`、`.parser`、`.security`、`.idempotency`、`.queue`、`.render`、`.service`、`.routes`、`.app`；
    7. 不得修改 `backend/tests/test_engine.py` 的白名单。
  - 验收：
    1. 违规项为 0；
    2. `python -m unittest tests.test_engine.EngineImportDirectionTests.test_import_direction -v`（或该用例实际类名）通过；
    3. 引擎包内无 `fastapi`/`uvicorn`/`httpx`/`starlette`/`pydantic`（只读扫描，不修改）；
    4. 审计脚本未落盘到仓库。
  - 回执：按 1.3 模板，附违规项计数与用例通过证据。

- [ ] **审计写操作、网络与危险调用**
  - 前置依赖：7.1（A）
  - 输入：18 个新增产品文件
  - 审计规则：
    1. 除日志（`logging`）与 `live` 出站（经 `HttpClient`）外，**不得**出现 `open(..., "w"/"a"/"x")`、`Path.write_text`、`Path.write_bytes`、`shutil.*`、`tempfile.*`（测试除外）、`os.remove`、`os.rename`、`os.makedirs`；
    2. 不得出现 `subprocess`、`os.system`、`os.popen`、`git clone`、`git fetch`、`git pull`、`ls-remote`；
    3. 不得出现 `socket.socket(` 直接使用、`urllib.request`、`requests`；
    4. 不得出现 `eval(`、`exec(`、`pickle`、`yaml.load`；
    5. 日志调用不得输出 `secret`、`token`、`Authorization`、`raw_body`、`manifest_text`、`markdown`、`repo_root`；
    6. 禁止读取 `REPOGUARD_WEBHOOK_SECRET` / `REPOGUARD_OPENAPI_TOKEN` 之外的密钥源；密钥只允许出现在 HMAC 计算与出站认证头。
  - 验收：
    1. 违规项为 0；
    2. 18 个文件中无被检查仓库写入路径；
    3. 日志字段审计通过（用关键词扫描 `secret`、`token`、`raw_body`、`manifest_text`、`markdown` 的日志拼接上下文）；
    4. 无 `subprocess`/`os.system`/`git` 调用。
  - 回执：按 1.3 模板。

### 7.2 全量回归与冻结门禁

- [ ] **（2-A）重算 13 个冻结文件哈希并比对**
  - 前置依赖：7.1（A）（B）
  - 输入：13 个冻结文件（路径见 2.2）+ `requirements.txt` + `static/index.html` + `tests/` 既有文件
  - 输出：差异文件数必须为 0
  - 验收：
    1. 13 个冻结文件 SHA-256 与 2.2 清单逐条一致，差异 0；
    2. `requirements.txt` 哈希仍为 `18a816cd88636be844e7cd3a6662b2cdc2e13324420031f082a331a520b4bbcf`；
    3. `static/index.html`、`app/api/**`、`app/health/**`、`app/readme/**`、`app/shared/**` 哈希不变；
    4. `tests/` 既有 17 个 `test_*.py`、`__init__.py`、`fixtures/sample_changes.txt` 哈希不变；
    5. 新增文件只出现在第 2 节目录树所列路径。
  - 回执：按 1.3 模板，附差异计数与新增文件清单。

- [ ] **（2-B）全量基线回归（310 口径）**
  - 前置依赖：7.2（A）
  - 命令：`cd backend && python -m unittest discover -s tests -v`
  - 验收：
    1. 总数 = 310 + 新增用例数，**不得少于 310**；
    2. `failures = 0`、`errors = 0`（新增）；
    3. 支持符号链接环境：既有 3 条 skipped 的 `reason` 与 2.2 记录一致（1 条性能 + 2 条符号链接）；
    4. 当前沙箱：2 条既有符号链接用例若 failed/error，单列为「既有平台异常」，**不计入新增失败**，且**未修改这两条测试**；
    5. 若新增用例产生 failed/error → 门禁失败，停止。
  - 回执：按 1.3 模板，附 `Ran` 行、`failures`、`errors`、`skipped` 与既有异常单列。

- [ ] **（2-C）CLI 12 passed**
  - 前置依赖：7.2（B）
  - 命令：`cd backend && python -m unittest tests.test_cli -v`
  - 验收：
    1. `Ran 12 tests` 且 `OK`；
    2. `python -m app.core.rules.engine --format json` 输出退出码 0、键集合与 2.2 基线一致；
    3. `python -m app.health.cli`、`python -m app.readme.cli` 参数、退出码、输出格式不变（抽查 `--help` 与一次运行）；
    4. 未修改 `tests/test_cli.py`（哈希一致）。
  - 回执：按 1.3 模板。

- [ ] **（2-D）阶段 2 API 回归**
  - 前置依赖：7.2（C）
  - 命令：`cd backend && python -m unittest tests.test_api -v`
  - 验收：
    1. 全部通过，`failures = 0`、`errors = 0`；
    2. `GET /`、`GET /api/health`、`POST /api/review` 行为与错误码不变；
    3. 阶段 2 路由集合不含 `/webhook`、`/healthz`；
    4. `backend/app/static/index.html` 哈希不变。
  - 回执：按 1.3 模板。

- [ ] **（2-E）依赖与配置零改动**
  - 前置依赖：7.2（D）
  - 验收：
    1. `python -m unittest tests.test_engine.EngineRequirementsTests.test_requirements_txt -v`（或该用例实际类名）通过；
    2. `requirements.txt` 7 行、三段式结构不变、哈希不变；
    3. 未新增任何第三方依赖行、未修改测试依赖段；
    4. 运行时 `import httpx` 在已安装环境下可用（复用 `httpx==0.28.1`）。
  - 回执：按 1.3 模板。

- [ ] **（2-F）新增用例计数与 W 矩阵勾选**
  - 前置依赖：7.2（E）
  - 输入：8 个测试文件
  - 输出：W01–W66 勾选表（见附录 A）、新增用例计数
  - 验收：
    1. 每个 W 编号都有对应用例名且实际存在；
    2. 除 6.8（B）可选回环外，无新增 skipped；若存在其它 skip，必须说明原因并判定是否违规；
    3. 新增用例总数与实测 `Ran` 差值一致（`Ran 总数 - 310 = 新增用例数`）；
    4. 矩阵中「驱动方式」与实际代码一致（抽查 10 条）。
  - 回执：按 1.3 模板，附矩阵勾选结果。

### 7.3 离线实测与零网络 / 零真实端口验证

- [ ] **（3-A）零网络验证**
  - 前置依赖：7.2（F）
  - 方法：
    1. 临时设置 `PYTHONHTTPSVERIFY` 无关项无效，改用进程级 socket 拦截：在执行环境中用 `python -m unittest discover -s tests -v` 前设置不可用代理或用测试内 patch；
    2. 对新增 8 个测试文件全部执行 `patch("socket.socket", side_effect=AssertionError)` 场景（已在用例内）；
    3. 抽查 `disabled` 模式下一整条入站请求，断言无 socket、无 DNS。
  - 验收：
    1. 全部新增用例在 socket 拦截下通过（可选回环用例除外，且默认 skip）；
    2. 无公网访问记录、无 DNS 解析；
    3. `outbound` 只发生在 `mock`（进程内）与 `live`（仅 `MockTransport` 测试替身）。
  - 回执：按 1.3 模板。

- [ ] **（3-B）零真实端口验证**
  - 前置依赖：7.3（A）
  - 方法：执行前后对比监听端口（`netstat -ano | findstr LISTENING`），并静态扫描 8 个测试文件与 18 个产品文件中的 `uvicorn.run` / `bind(` / `listen(`；
  - 验收：
    1. 测试执行期间无新增监听端口；
    2. 测试文件中 `uvicorn.run` 出现次数为 0；
    3. 唯一例外是 6.8（B）可选回环用例，且默认 skip、仅 `127.0.0.1:0`；
    4. 产品代码 `__main__.py` 的 `uvicorn.run` 允许存在，但测试不得调用。
  - 回执：按 1.3 模板。

- [ ] **（3-C）离线实测人工验证**
  - 前置依赖：7.3（B）
  - 步骤：
    1. `cd backend` → `set REPOGUARD_WEBHOOK_SECRET=<随机假值>`（cmd）或 `$env:...`（PowerShell）→ `python -m app.webhook`；
    2. 另开终端，用 `python` 一次性脚本生成签名并发 `POST http://127.0.0.1:8010/webhook`（人工验证，**不写入仓库**）；
    3. 观察 202、启动日志、`GET /healthz` 200、`disabled` 模式零出站；
    4. 停止进程，确认优雅停机日志。
  - 验收：
    1. 默认监听 `127.0.0.1:8010`；
    2. 202 响应 6 字段、`/healthz` 13 字段；
    3. 日志无密钥/令牌/绝对路径；
    4. `disabled` 模式下无出站连接（可用系统工具确认）；
    5. 人工验证脚本不落盘、不提交。
  - 回执：按 1.3 模板。

### 7.4 中文使用文档

- [ ] **新增中文使用说明**
  - 完整路径：`docs/webhook_openapi_usage.md`（仓库根目录下 `docs/`；若目录不存在则创建）
  - 前置依赖：7.3（A）（B）（C）
  - 输入：`design.md` 2.5.8 环境变量总表、2.5.4 幂等局限、7.3 故障排查所需错误码
  - 输出：一份可照做的中文文档
  - 必须包含章节：
    1. **能力与边界**：独立进程、不挂阶段 2、默认 `127.0.0.1:8010`、`disabled` 零出站；
    2. **快速启动**：`cd backend && python -m app.webhook`；环境变量设置方式（cmd 与 PowerShell 各一例）；
    3. **环境变量总表**：服务与接收、事件与解析、幂等/队列/检查、OpenAPI 出站、测试专用五组；标注默认值与范围；
    4. **HMAC 签名**：算法 `HMAC-SHA256`、签名串 `timestamp + "." + raw_body`、头名与前缀、10/13 位时间戳、重放窗口、密钥轮换四步操作流程；
    5. **三种模式**：`disabled`/`mock`/`live` 的行为、记录状态、切换方法、`live` 缺配置 fail-closed；
    6. **评论回写**：请求体模板 `{markdown}` 语义（JSON 字符串字面量位置）、endpoint 占位符、认证头、成功状态码、来源标记；
    7. **失败与降级回写**：失败说明、降级说明、`notify_on_failure` / `notify_on_clean`、「不伪装成功」口径；
    8. **幂等局限**：单实例内存去重、重启清空、多实例/负载均衡失效、可能重复回评、缓解建议（单实例、粘性路由、来源标记识别），**明确不引入 Redis/数据库**；
    9. **离线测试**：`cd backend && python -m unittest discover -s tests -v`、`ASGITransport`/`MockTransport`/内存 mock、可选回环开关 `REPOGUARD_WEBHOOK_E2E_LOOPBACK=1`、默认 skip；
    10. **故障排查**：401 四类、403、409、413、415、422、429、500、502/504、503 四类的排查步骤与对应环境变量；
    11. **假设清单**：A01～A17 摘录与本阶段「可配置适配层」原则；
    12. **已知局限**：`httpx` 位于测试依赖段、单实例幂等、不做 DNS 解析的残留风险、Windows 符号链接用例为既有平台波动。
  - 验收：
    1. 文档为简体中文，命令块可直接复制执行；
    2. 覆盖上述 12 个章节，无缺项；
    3. 全部示例使用假密钥/假令牌（形如 `<请替换为随机值>`），**不含真实凭据**；
    4. 明确写出「默认 `disabled` 零出站」「重启/多实例可能重复回评」「不引入 Redis/数据库」；
    5. 文档不修改任何既有 `.md`；仅新增该文件；
    6. 文档中的命令与 `design.md` 2.5.8 一致（抽查 5 条）。
  - 回执：按 1.3 模板。

### 7.5 最终交付核对

- [ ] **完成交付前总核对**
  - 前置依赖：7.4
  - 输入：全部执行记录、W 矩阵、哈希清单、回归结果
  - 验收（逐项打勾，缺一不可）：
    1. **18 个产品文件**全部存在且路径与第 2 节目录树一致；文件内无实现代码以外的临时脚本；
    2. **8 个测试文件** + `webhook_helpers.py` + 4 个 fixture 全部存在；
    3. **W01–W66** 全部有对应用例并通过（6.8（B）可选回环默认 skip 且已记录）；
    4. **310 条基线**不减少、无新增 failed/error；既有 2 条符号链接异常单列记录且测试未改；
    5. **13 个冻结文件** SHA-256 差异 0；`requirements.txt` 哈希不变；`static/index.html` 哈希不变；
    6. **CLI 12 passed**、**阶段 2 test_api 全过**、路由集合不含 `/webhook`/`/healthz`；
    7. **导入方向审计**违规 0、**写操作审计**违规 0；
    8. **零网络**、**零真实端口**（可选回环除外）证据齐备；
    9. **中文文档**已新增且 12 章节齐全；
    10. **未修改** `spec.md`、`design.md`、任何既有源码/测试/配置/静态资源/历史规格；
    11. 交付报告包含：实际产出路径清单、验收结论、未修改清单、失败/降级项、下一阶段建议（`httpx` 依赖段整理、共享去重立项、平台官方协议核实）；
    12. 交付后**不继续编码**，等待用户确认。
  - 回执：按 1.3 模板，附完整证据索引。

---

## 附录 A：W01–W66 覆盖矩阵（逐条）

| 编号 | 用例名 | 所属文件 | 驱动方式 | 关键断言 |
|------|--------|---------|---------|---------|
| W01 | `test_signature_ok` | `test_webhook_signature.py` | ASGITransport | 正确签名 → 202，`status=accepted` |
| W02 | `test_signature_missing` | 同上 | ASGITransport | 401 `WEBHOOK_SIGNATURE_MISSING`；请求体 `yield` 次数 0 |
| W03 | `test_signature_invalid` | 同上 | 直接函数 | 401 `WEBHOOK_SIGNATURE_INVALID` |
| W04 | `test_signature_body_tampered` | 同上 | 直接函数 | 篡改 1 字节 → 401 |
| W05 | `test_signature_prefix_optional` | 同上 | 直接函数 | `prefix=""` 时裸 hex 通过；默认前缀下裸 hex 拒绝 |
| W06 | `test_signature_wrong_length` | 同上 | 直接函数 | 长度 63/65 → 401 |
| W07 | `test_timestamp_missing` | 同上 | 直接函数 | 401 `WEBHOOK_TIMESTAMP_MISSING` |
| W08 | `test_timestamp_expired` | 同上 | 直接函数 | 落后超窗 → 401 `WEBHOOK_TIMESTAMP_EXPIRED` |
| W09 | `test_timestamp_future` | 同上 | 直接函数 | 超前超窗 → 401 `WEBHOOK_TIMESTAMP_INVALID` |
| W10 | `test_timestamp_millis` | 同上 | 直接函数 | 13 位毫秒识别，`timestamp_unit="milliseconds"` |
| W11 | `test_secret_unconfigured` | 同上 | ASGITransport | 503 `WEBHOOK_SECRET_NOT_CONFIGURED`；不读体 |
| W12 | `test_secret_rotation_previous` | 同上 | 直接函数 | 上一版本密钥通过，`used_previous=True` |
| W13 | `test_json_invalid` | `test_webhook_parser.py` | 直接函数 | 验签后非法 JSON → 400 `WEBHOOK_INVALID_JSON` |
| W14 | `test_content_type_rejected` | 同上 | ASGITransport | 415 `WEBHOOK_UNSUPPORTED_MEDIA_TYPE`，不读体 |
| W15 | `test_payload_too_large_content_length` | 同上 | ASGITransport | 413 `WEBHOOK_PAYLOAD_TOO_LARGE`，不读体 |
| W16 | `test_payload_too_large_chunked` | 同上 | ASGITransport | 分块读取超限 → 413 |
| W17 | `test_event_type_allowed` | 同上 | 直接函数 | 合法类型 `classify_event_kind()` 非 `None` |
| W18 | `test_event_type_ignored` | 同上 | ASGITransport | 202 `ignored`、`action=skipped`、不检查不回评 |
| W19 | `test_event_invalid_missing_pr` | 同上 | 直接函数 | 422 `WEBHOOK_EVENT_INVALID`，`detail` 只含字段名 |
| W20 | `test_field_map_custom` | 同上 | 直接函数 | 自定义 `field_map` 覆盖默认路径 |
| W21 | `test_event_id_fallback_delivery_header` | 同上 | 直接函数 | 幂等键来源 `delivery_header` |
| W22 | `test_event_id_fallback_content_hash` | 同上 | 直接函数 | `content_hash` 64 位 hex，两次一致 |
| W23 | `test_changed_files_from_payload` | 同上 | 直接函数 | 来源 `payload`，不调 OpenAPI |
| W24 | `test_changed_files_from_lists` | 同上 | 直接函数 | `A`/`M`/`D` 状态正确、去重保序 |
| W25 | `test_changed_files_from_openapi` | 同上 | 直接函数 | `should_fetch_via_openapi=True`，来源 `openapi` |
| W26 | `test_changed_files_unavailable` | 同上 | 直接函数 | `available=False`，来源 `none`，禁调引擎 |
| W27 | `test_illegal_paths_filtered` | 同上 | 直接函数 | `..`/绝对/盘符/UNC 剔除并计数 |
| W28 | `test_manifest_construction` | 同上 | 直接函数 | 行格式、空格路径、`entry_count`、上限判定 |
| W29 | `test_repo_mapping_allowed` | `test_webhook_service.py` | 直接函数 + 临时仓库 | 全名/短名/映射表均命中 |
| W30 | `test_repo_forbidden` | 同上 | 直接函数 | 403 `WEBHOOK_REPO_FORBIDDEN`，无 FS 探测 |
| W31 | `test_no_remote_clone` | 同上 | 静态扫描 | 无 `clone`/`subprocess`/`os.system` |
| W32 | `test_run_check_called_once` | 同上 | InMemory fake runner | `calls == 1`，`config is None` |
| W33 | `test_no_module_imports` | 同上 | 静态扫描 | 无四检查模块导入 |
| W34 | `test_engine_degraded_passthrough` | 同上 | InMemory | 评论含降级模块与中文原因 |
| W35 | `test_engine_exception` | 同上 | InMemory | 记录 `failed`，无「未发现问题」 |
| W36 | `test_engine_input_error` | 同上 | InMemory | 保留「输入错误」并说明 |
| W37 | `test_task_timeout` | 同上 | InMemory + FrozenClock | 超时记录、不调引擎 |
| W38 | `test_queue_full` | 同上 | ASGITransport（容量 1 预占满） | 429 `WEBHOOK_BUSY`，占位回滚 |
| W39 | `test_duplicate_event` | `test_webhook_idempotency.py` | ASGITransport | 202 `duplicate`，不重复回评 |
| W40 | `test_concurrent_duplicate` | 同上 | 直接函数 + Barrier | 并发仅 1 个 `NEW` |
| W41 | `test_event_conflict` | 同上 | ASGITransport | 409 `WEBHOOK_EVENT_CONFLICT`，保留首次 |
| W42 | `test_idempotency_ttl_expired` | 同上 | 直接函数 + FrozenClock | TTL 后可重新处理 |
| W43 | `test_idempotency_capacity_eviction` | 同上 | 直接函数 | 淘汰计数、活跃 `PROCESSING` 不淘汰 |
| W44 | `test_retry_failed_disabled_by_default` | 同上 | 直接函数 | 默认 `DUPLICATE_FAILED`；开关开 `RETRY_ALLOWED` |
| W45 | `test_comment_structure` | `test_webhook_comment.py` | 直接函数 | 必须修改在前、统计一致 |
| W46 | `test_comment_truncation` | 同上 | 直接函数 | `len <= limit`、未展示计数、保留 marker |
| W47 | `test_comment_marker` | 同上 | 直接函数 | marker 在正文末尾 |
| W48 | `test_comment_redaction` | 同上 | 直接函数 | 令牌/绝对路径 → `****` |
| W49 | `test_comment_empty_vs_not_executed` | 同上 | 直接函数 | 空结果「未发现问题」；未执行不含该文案 |
| W50 | `test_openapi_disabled_no_request` | `test_webhook_openapi.py` | InMemory | 零出站，`delivery_status=skipped` |
| W51 | `test_openapi_mock_delivered` | 同上 | InMemory | 评论记录，`mock_delivered` |
| W52 | `test_openapi_timeout_retry` | 同上 | MockTransport | `attempts=3`，`OPENAPI_TIMEOUT` |
| W53 | `test_openapi_429_retry` | 同上 | MockTransport | 429→成功，`attempts=2` |
| W54 | `test_openapi_5xx_retry_then_fail` | 同上 | MockTransport | `OPENAPI_UNAVAILABLE`，不伪装成功 |
| W55 | `test_openapi_401_no_retry` | 同上 | MockTransport | `attempts=1`，`OPENAPI_AUTH_FAILED` |
| W56 | `test_openapi_404_no_retry` | 同上 | MockTransport | `attempts=1`，`OPENAPI_NOT_FOUND` |
| W57 | `test_openapi_live_incomplete` | 同上 | ASGITransport + 直接函数 | 503 `OPENAPI_NOT_CONFIGURED`，健康降级 |
| W58 | `test_openapi_host_forbidden` | 同上 | MockTransport（0 次调用） | `OPENAPI_HOST_FORBIDDEN` |
| W59 | `test_openapi_no_redirect` | 同上 | MockTransport | 3xx → `OPENAPI_REDIRECT_FORBIDDEN`，`attempts=1` |
| W60 | `test_health_ok` | `test_webhook_api.py` | ASGITransport | 200，13 字段，`no-store` |
| W61 | `test_health_degraded` | 同上 | ASGITransport | 503（密钥/引擎/live 缺配置） |
| W62 | `test_health_method_not_allowed` | 同上 | ASGITransport | 405 `METHOD_NOT_ALLOWED` |
| W63 | `test_phase2_routes_unchanged` | 同上 | 直接导入 | 路由集合不变，不含 `/webhook`/`/healthz` |
| W64 | `test_cli_regression` | 同上 | subprocess（无端口） | CLI 退出码 0、JSON 键集合不变 |
| W65 | `test_no_network_outside_mock` | 同上 | ASGITransport + socket 补丁 | disabled/mock 均无真实连接 |
| W66 | `test_offline_e2e` | `test_webhook_e2e_offline.py` | ASGITransport + InMemory + 真实临时仓库 | 202→`mock_delivered`，marker，`calls==1` |

**覆盖率自查**：66 条编号全覆盖；无编号空缺；无重复编号；每条均可定位到唯一文件与唯一用例名。

---

## 附录 B：18 个产品源码文件与依赖顺序

| 序号 | 仓库相对路径 | 任务 | 依赖 |
|------|-------------|------|------|
| 1 | `backend/app/integrations/models.py` | 3.1 | 2.2 |
| 2 | `backend/app/integrations/client.py` | 3.2 | 3.1 |
| 3 | `backend/app/integrations/openapi.py` | 3.3 | 3.1、3.2 |
| 4 | `backend/app/integrations/mock.py` | 3.4 | 3.1、3.3 |
| 5 | `backend/app/integrations/__init__.py` | 3.5 | 3.1、3.3、3.4 |
| 6 | `backend/app/webhook/models.py` | 4.1 | 3.1 |
| 7 | `backend/app/webhook/settings.py` | 4.2 | 4.1 |
| 8 | `backend/app/webhook/signature.py` | 4.3 | 4.2 |
| 9 | `backend/app/webhook/parser.py` | 4.4 | 4.2 |
| 10 | `backend/app/webhook/security.py` | 4.5 | 4.2 |
| 11 | `backend/app/webhook/idempotency.py` | 4.6 | 4.1 |
| 12 | `backend/app/webhook/render.py` | 4.7 | 4.1 |
| 13 | `backend/app/webhook/queue.py` | 4.8 | 4.1 |
| 14 | `backend/app/webhook/service.py` | 4.9 | 4.2～4.8 |
| 15 | `backend/app/webhook/routes.py` | 4.10 | 4.9 |
| 16 | `backend/app/webhook/app.py` | 4.11 | 4.10 |
| 17 | `backend/app/webhook/__init__.py` | 4.12（A） | 4.11 |
| 18 | `backend/app/webhook/__main__.py` | 4.12（B） | 4.12（A） |

**测试与文档文件（9 + 4 + 1）**：8 个 `test_webhook_*.py`、`tests/webhook_helpers.py`、4 个 fixture、`docs/webhook_openapi_usage.md`。

---

## 附录 C：错误码 → 用例覆盖对照

| HTTP | error.code | 覆盖用例 |
|------|-----------|---------|
| 400 | `WEBHOOK_INVALID_JSON` | W13 |
| 401 | `WEBHOOK_SIGNATURE_MISSING` | W02 |
| 401 | `WEBHOOK_SIGNATURE_INVALID` | W03、W04、W05、W06 |
| 401 | `WEBHOOK_TIMESTAMP_MISSING` | W07 |
| 401 | `WEBHOOK_TIMESTAMP_INVALID` | W09 |
| 401 | `WEBHOOK_TIMESTAMP_EXPIRED` | W08 |
| 403 | `WEBHOOK_REPO_FORBIDDEN` | W30 |
| 403 | `OPENAPI_HOST_FORBIDDEN` | W58 |
| 404 | `NOT_FOUND` | W60～W62 所在文件的路径断言（404 分支） |
| 405 | `METHOD_NOT_ALLOWED` | W62 |
| 409 | `WEBHOOK_EVENT_CONFLICT` | W41 |
| 413 | `WEBHOOK_PAYLOAD_TOO_LARGE` | W15、W16 |
| 415 | `WEBHOOK_UNSUPPORTED_MEDIA_TYPE` | W14 |
| 422 | `WEBHOOK_EVENT_INVALID` | W19、W26 |
| 429 | `WEBHOOK_BUSY` | W38 |
| 500 | `WEBHOOK_INTERNAL_ERROR` | W60～W62 所在文件的未预期异常分支 |
| 502 | `OPENAPI_DELIVERY_FAILED` | W54 同步模式分支（若实现同步映射） |
| 503 | `WEBHOOK_DISABLED` | W61 |
| 503 | `WEBHOOK_SECRET_NOT_CONFIGURED` | W11、W61 |
| 503 | `ENGINE_UNAVAILABLE` | W61 |
| 503 | `OPENAPI_NOT_CONFIGURED` | W57 |
| 504 | `OPENAPI_TIMEOUT` | W52 同步模式分支（若实现同步映射） |

> 说明：502/504 仅在同步模式对外返回；异步模式通过 `DeliveryRecord.delivery_status="failed"` + `error_code` 观测，W52/W54 至少覆盖一种映射方式，并在用例中断言「未伪装成功」。

---

## 附录 D：门禁命令清单（可直接照做）

```text
# 1) 改动前基线
cd backend
python -m unittest discover -s tests -v

# 2) 冻结文件哈希（逐文件）
certutil -hashfile app\core\rules\engine.py SHA256

# 3) 单文件编译
python -m py_compile app\webhook\service.py

# 4) 单文件测试
python -m unittest tests.test_webhook_signature -v
python -m unittest tests.test_webhook_parser -v
python -m unittest tests.test_webhook_service -v
python -m unittest tests.test_webhook_idempotency -v
python -m unittest tests.test_webhook_comment -v
python -m unittest tests.test_webhook_openapi -v
python -m unittest tests.test_webhook_api -v
python -m unittest tests.test_webhook_e2e_offline -v

# 5) 全量回归
python -m unittest discover -s tests -v

# 6) CLI 回归
python -m unittest tests.test_cli -v
python -m app.core.rules.engine --format json

# 7) 阶段 2 回归
python -m unittest tests.test_api -v

# 8) 依赖与导入断言
python -m unittest tests.test_engine -v

# 9) 启动（人工验证，非测试）
python -m app.webhook
```

---

## 附录 E：任务完成回执模板

见 1.3。每个子任务必须逐项填写，缺项视为未完成；失败项必须写明触发条件、实际结果与停止位置。

---

## 附录 F：交付自查（防止口径冲突）

| 检查项 | 要求 | 结论 |
|--------|------|------|
| 测试运行器 | 全篇只出现 `python -m unittest`；无其他运行器示例 | 通过 |
| 入站测试通道 | 全篇只用 `httpx.ASGITransport`；同步测试客户端仅以「禁止」形式出现 | 通过 |
| 出站测试通道 | 只允许 `httpx.MockTransport`、内存 adapter、进程内 mock 服务 | 通过 |
| 真实端口 | 仅 6.8（B）可选回环且默认 skip、仅 `127.0.0.1:0`；其余禁止 | 通过 |
| 网络 | 默认零网络；`disabled` 零出站 | 通过 |
| 依赖 | 不新增第三方依赖；`requirements.txt` 哈希不变 | 通过 |
| 冻结文件 | 13 个文件哈希差异 0 | 通过 |
| 基线 | 310 条不减少；无新增 failed/error；既有 2 条符号链接异常只记录 | 通过 |
| 阶段 2 | 路由集合与行为不变 | 通过 |
| 文档 | 仅新增 `docs/webhook_openapi_usage.md` | 通过 |
| 代码 | 本文档无实现代码，仅有接口签名 | 通过 |

---

**文档结束**：本清单共 32 个主任务（3.x～7.x）、44 个可执行子任务；覆盖 18 个产品源码文件、8 个测试文件、1 个辅助模块、4 个 fixture、1 份中文文档；W01–W66 全覆盖。
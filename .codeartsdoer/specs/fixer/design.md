# 修复辅助层（fixer）设计 design

> 依据：`.codeartsdoer/specs/fixer/spec.md`（2026-11-17 修订版，480 行）。
> 本文只描述设计，不含产品实现代码，不生成 tasks.md。
> 基线事实（2026-11-17 本地实测）：后端既有全量 `Ran 452 tests` → `OK (skipped=4)`；既有测试文件 29 个；`backend/app/api/app.py` 当前 194 行，`app.py.orig` 187 行。

---

# 一、需求与存量功能关系

## 1.1 复用 / 扩展 / 新增

| 能力 | 处理方式 | 存量位置（真实行号） | 说明 |
|---|---|---|---|
| 仓库白名单与路径校验 | **复用** | `backend/app/api/security.py:96-154` `resolve_repo_root()` | fixer 不重写仓库解析；额外做 `file_path` / `backup_dir` / `backup_path` 归属校验 |
| 路径错误类型 | **复用** | `backend/app/api/security.py:16-28` `RepoPathError` | `app.py:90-92` 已有处理器，fixer 直接抛出即可 |
| 统一错误体 | **复用** | `backend/app/api/routes.py:41-54` `ApiError`；`backend/app/api/schemas.py:41-53` `error_payload()` | `app.py:86-88` 已有 `ApiError` 处理器 |
| 请求字段校验 | **复用** | `backend/app/api/app.py:94-102` `RequestValidationError` 处理器 | 返回 422 `VALIDATION_ERROR` |
| 405 / 404 映射 | **复用** | `backend/app/api/app.py:104-115` | fixer 不需要自建 HTTP 异常处理器 |
| 请求 ID / 安全响应头 / no-store | **复用** | `backend/app/api/app.py:55-82` | fixer 只返回 `JSONResponse`，头部由中间件补齐 |
| 只读看板 GET 契约 | **不改** | `backend/app/dashboard/router.py:250-431` | 既有 `repos/overview/issues/structure/history` 行为不变 |
| 链接解析规则 | **只读复用** | `backend/app/core/rules/link_check.py:21-25, 67-152, 176-322` | 复用正则与 `LinkRecord` 口径，不修改引擎 |
| ASGI 测试客户端 | **复用** | `backend/tests/webhook_helpers.py:124-145` | `WebhookASGIClient.request("POST", path, json=...)` |
| 测试零端口事件循环垫片 | **复用** | `backend/tests/webhook_helpers.py:17-50` | 与既有 API 测试一致 |
| 目录选择 IPC | **复用** | `desktop/main/main.js:15-23`；`desktop/main/preload.js:5-8` | `window.repoguard.pickDirectory()`，不新增 IPC |
| HTTP JSON 客户端 | **复用** | `frontend/src/api/client.js:54-116` | 已支持 `method` / `body`，fixer 只需新增 `api/fixer.js` |
| 错误码中文映射 | **扩展** | `frontend/src/api/client.js:3-17` | 不改 `client.js`；`fixer.js` 内补充 `FIXER_*` 映射 |
| 看板问题明细 | **扩展** | `frontend/src/views/IssuesView.vue:333-358` | 仅在 `DataTable` 的 `#detail` 插槽挂载修复入口 |
| fixer 后端包 | **新增** | `backend/app/fixer/**` | 补丁、校验、备份、应用、回滚、锁、审计 |
| fixer 前端 API | **新增** | `frontend/src/api/fixer.js` | preview / apply / rollback 三个 POST |
| diff 弹窗 | **新增** | `frontend/src/components/FixPreviewDialog.vue` | 单文件组件，含触发按钮、补丁列表、diff 预览 |
| 使用文档 | **新增（后续交付）** | `docs/fixer_usage.md` | design 只登记范围，不在本轮生成 |

## 1.2 读写边界矩阵

| 层 | 读 | 写 | 边界 |
|---|---|---|---|
| `core/rules/**` | 是 | 否 | 15 项哈希零改动 |
| `app/dashboard/**` GET | 是 | 否 | 既有 GET 行为不变 |
| `app/api/routes.py` | 是 | 否 | 只读巡检契约不变 |
| `app/fixer/**` | 是 | **是**（仅用户确认后） | 仅桌面模式可用 |
| 备份目录 | 否 | 是 | 必须在被巡检仓库之外 |
| 被巡检仓库 | 是 | 是（仅目标 Markdown 行） | `file_path` 归属校验 + 符号链接拦截 |

## 1.3 存量偏差（本设计登记，不在本轮修复）

1. **app.py 相对 stage5 基线的存量增量为 +8/-1**：相对 app.py.orig 实测 added=8 removed=1（详见 2.3）。该存量差异已按方案 A 对齐 spec：fixer 阶段以 stage6 快照为基线、自身 +2/-0，stage5 存量 +8/-1 不计入 fixer 增量（见第十三节 S-01）。
2. **`/api/dashboard/check-repo` 返回绝对路径**：`backend/app/dashboard/router.py:296-314` 的响应包含 `"path": str(root)`。这是阶段 5 之后的存量偏差，与 dashboard 脱敏口径冲突；fixer 不依赖该接口，不在本轮修改。
3. **`client.js` 默认超时 45 秒**：`frontend/src/api/client.js:1`。fixer 的 apply 可能包含备份与多文件写入，`api/fixer.js` 显式传 `timeoutMs: 60000`，不改 `client.js`。

---

# 二、存量契约分析

## 2.1 `resolve_repo_root()`

位置：`backend/app/api/security.py:96-154`。

签名：
```python
def resolve_repo_root(raw: str, settings: WebSettings) -> Path
```

入参：
- `raw`：仓库绝对路径或标识/相对名；长度上限 `MAX_REPO_LENGTH=512`（`security.py:9`）。
- `settings`：`WebSettings`，含 `desktop_mode`、`allowed_repo_roots`、`default_repo`（`backend/app/api/settings.py:45`）。

出参：
- `Path`：解析后的真实仓库根（`resolve(strict=False)`）。
- **仅服务端内部使用**；fixer 响应必须转换为 `repo_label`，不得回传该路径。

异常（`RepoPathError`，`security.py:16-28`）：
- `INVALID_REPO_PATH` / 400：空、超长、控制字符、包含 `://`、非绝对路径（桌面模式）、未配置默认仓库。
- `REPO_FORBIDDEN` / 403：`..` 段、设备/UNC 路径、系统敏感目录、允许根之外。
- `REPO_NOT_FOUND` / 404：目录不存在或不是目录。

校验序列（`security.py:97-153`）：
1. `strip()`、长度、控制字符、`://`；
2. `has_parent_segment()`（31-33）、`is_device_or_unc_path()`（40-41）；
3. `desktop_mode=True` 分支（110-124）：必须绝对路径；`_is_protected_system_dir()` 拒绝盘根与 `Windows/Program Files/ProgramData`（49-70）；目录必须存在；
4. 非桌面模式：默认令牌、绝对路径、或 `default_root / token`；`is_within_allowed_roots()` 用 `os.path.commonpath`（73-93）比较；
5. 返回真实路径。

fixer 的约束：
- 调用后只拿 `Path`；对外只输出 `repo_label`。
- 桌面模式下 `repo` 必须是绝对路径（`security.py:111-117`）；前端从看板当前仓库绝对路径传入，符合桌面壳的实际调用方式。
- 非桌面模式 fixer 端点 404，不进入该分支。

## 2.2 `link_check` 的 link-005 覆盖口径

位置：`backend/app/core/rules/link_check.py`。

正则（21-25）：
- `INLINE_RE`（21）：`(!?)\[([^\]\n]*)\]\(([^)\n]*)\)`，覆盖 inline 与 image。
- `DEFINITION_RE`（23）：`^\s*\[([^\]\n]+)\]:\s*(\S.*)?$`，覆盖 reference definition。
- `REFERENCE_RE`（22）：`[...][...]`，kind=`reference`。
- `BARE_RE`（24）：裸 URL。

`extract_links()`（67-152）：
- inline/image：`kind` 由 `!` 前缀区分（74）；
- reference：`target=""`、`kind="reference"`（92-103）；
- definition：`target = group(2).strip().split()[0]`（121-137），**title 被丢弃**，只保留 target；
- 排序按 `(line_no, match.start())`（151）。

`validate_links()`（176-322）：
- reference 缺失定义 → link-003，随后 `continue`（186-197）；
- `target = link.target.strip()`；`wrapped = target.startswith("<") and target.endswith(">")`（199-202）；
- 空目标（inline/image/definition）→ link-001（216-226）；
- **link-005**（228-238）：`" " in target and not wrapped`；建议文案为 `%20` 或尖括号；
- link-005 命中后 `continue`，不会再产出 link-004/006/007（238）。

fixer 的锁定口径：
- 只处理 `inline` / `image` / `definition`；`reference` 不生成 link-005 补丁。
- 尖括号包裹不处理。
- definition 只改 target，不改 title。
- 同一行多个命中合并为一个整行补丁。
- 解析以 `INLINE_RE` / `DEFINITION_RE` 为准；`extract_links()` 用于判定 kind 与尖括号，不直接用于替换（其 `raw` 截断 60、无列偏移，见 29-36、80、131）。

## 2.3 `app.py` 装配顺序与 +2 行边界

位置：`backend/app/api/app.py`（当前 194 行）。

关键结构：
- imports：16-27；其中 `from app.dashboard.router import router as dashboard_router` 在第 26 行。
- 中间件：55-82（request_id、安全头、`/api` no-store、结构化日志）。
- 异常处理器：85-120（`ApiError`、`RepoPathError`、`RequestValidationError`、`StarletteHTTPException`、`Exception`）。
- 静态挂载：123-132。
- CORS：135-144（`allow_methods=["GET","POST"]`）。
- lifespan：147-166。
- `create_app`：169-191；路由装配在 185-188：
  ```python
  _configure_middleware(app, effective_settings)   # 185
  _register_exception_handlers(app)                # 186
  app.include_router(router, prefix="/api")        # 187
  app.include_router(dashboard_router, prefix="/api/dashboard")  # 188
  _mount_static(app, effective_settings)           # 189
  ```

fixer 精确改动（fixer 自身 +2/-0）：
- 在 import 区第 27 行后新增 1 行：
  `from app.fixer.router import router as fixer_router`
- 在第 188 行后、189 行前新增 1 行：
  `app.include_router(fixer_router, prefix="/api/fixer")`
- 不改中间件、异常处理器、静态挂载、CORS、lifespan、既有路由。

**实测存量差异**（`app.py.orig` 187 行 → 当前 194 行）：
```text
baseline 187 current 194 added 8 removed 1
+from app.dashboard.router import router as dashboard_router
+from app.storage import init_db
-        app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
+        app.mount("/", StaticFiles(directory=settings.static_dir), name="static")
+            try:
+                init_db(settings.db_path)
+            except Exception:
+                LOGGER.exception("初始化数据库失败，历史记录功能将不可用")
+    app.include_router(dashboard_router, prefix="/api/dashboard")
```
fixer 再 +2/-0 后：当前 196 行，相对 `app.py.orig` 为 `+10/-1`。这与 spec 9.4 的 `+4/-0` 冲突，处置见第十三节。

## 2.4 错误码与处理器复用边界

- `ApiError`（`backend/app/api/routes.py:41-54`）：`code`、`status_code`、`message`、`detail`。
- `error_payload`（`backend/app/api/schemas.py:41-53`）：输出 `{"error": {"code","message","detail"?}, "request_id"}`。
- `app.py:86-88` 捕获 `ApiError`；`app.py:90-92` 捕获 `RepoPathError`；`app.py:94-102` 422；`app.py:104-115` 405/404；`app.py:117-120` 500 兜底。
- fixer **不新增全局异常处理器**；只抛 `ApiError` / `RepoPathError`。
- fixer 响应头由 `app.py:55-82` 中间件补齐（`X-Request-ID`、`X-Content-Type-Options`、`X-Frame-Options`、CSP、`/api` no-store），fixer 不重复实现。

## 2.5 dashboard router 的复用边界

- 可参考但**不导入私有函数**：`_raise_api`（33-36）、`_json_response`（95-105）、`_prepare`（167-247）均为 dashboard 包私有实现。
- fixer 自建 `_raise_api` 等价封装（运行期导入 `ApiError`）与 `_json_response`（仅 `JSONResponse`，头部交给中间件）。
- `get_web_settings`（39-43）的等价逻辑在 fixer 内重建：从 `request.app.state.settings` 读取；缺失 → `INTERNAL_ERROR` 500。
- `resolve_dashboard_repo`（`dashboard/service.py:204-216`）依赖 `list_repos`，桌面模式下 `allowed_repo_roots` 可能为空；fixer 直接使用 `resolve_repo_root`，不依赖 dashboard 令牌映射。
- `snapshot_key`（`dashboard/service.py:219-221`）可用于稳定哈希；fixer 的 `repo_label` 采用 `root.name` + 短哈希（见 6.2），不跨包调用。

---

# 三、总体架构

## 3.1 组件关系

```text
Electron 渲染进程（IssuesView）
  └─ FixPreviewDialog.vue
       └─ api/fixer.js ── POST /api/fixer/{preview,apply,rollback}
                              │
                              ▼
                        app/fixer/router.py（desktop_mode 依赖）
                              │
                              ▼
                        app/fixer/service.py
                 ┌────────────┼────────────┬─────────────┐
                 ▼            ▼            ▼             ▼
             paths.py     patches.py    backup.py     locks.py
                 │            │            │             │
                 └────────────┴─────┬──────┴─────────────┘
                                    ▼
                              audit.py（stdout JSON）
```

## 3.2 preview 时序

```text
浏览器/桌面壳            router            service             patches/paths
    │  POST preview        │                 │                     │
    ├─────────────────────►│                 │                     │
    │                      ├─ desktop 校验   │                     │
    │                      ├────────────────►│                     │
    │                      │                 ├─ 校验 repo/file_path ─►│
    │                      │                 ├─ 读取 UTF-8 文件 ────►│
    │                      │                 ├─ 定位 link-005 ──────►│
    │                      │                 ├─ 生成 old/new/diff ──►│
    │                      │◄────────────────┤                     │
    │◄─────────────────────┤ 200 patches     │                     │
```

## 3.3 apply 时序

```text
POST apply → 参数/desktop/JSON/上限校验 → 逐条重建补丁 + old_line 比对
           → 按文件分组去重 → 获取仓库锁（5 秒）→ 备份（copy2 + sha256）
           → 逐文件原子写（tmp + os.replace）→ 审计日志 → 200 applied/skipped/backups
```

## 3.4 rollback 时序

```text
POST rollback → 校验 backup_dir/backup_id/backup_path 归属
              → 获取仓库锁 → 逐文件比对 after_sha256
              → 冲突则 failed/409 → 原子覆盖 → 审计日志 → 200 restored/failed
```

## 3.5 线程模型

- 端点保持 `async def`，只做参数校验与结果封装。
- 文件 I/O、备份、补丁生成、锁等待全部经 `asyncio.to_thread(...)` 在 worker 线程执行，避免阻塞事件循环。
- 锁是 `threading.Lock`，在 worker 内获取；同一仓库的 apply/rollback 串行。

---

# 四、后端模块设计

## 4.1 文件清单

| 文件 | 职责 | 公开符号（设计签名） | 允许依赖 | 行数预算 |
|---|---|---|---|---|
| `backend/app/fixer/__init__.py` | 包标记与再导出 | `router` | `app.fixer.router` | ≤20 |
| `backend/app/fixer/errors.py` | fixer 错误码常量与抛错辅助 | `FIXER_INVALID_SELECTION` 等常量；`def raise_fixer(code: str, status: int, message: str, detail: str \| None = None) -> None` | 标准库、运行期 `app.api.routes.ApiError` | ≤70 |
| `backend/app/fixer/models.py` | 内部数据模型与序列化 | `@dataclass(frozen=True, slots=True) class Patch`、`Selection`、`BackupRecord`、`ApplyResult`、`RollbackResult`；`def to_dict(value: object) -> dict[str, object]` | 标准库 | ≤140 |
| `backend/app/fixer/schemas.py` | 请求体模型 | `class PreviewRequest(BaseModel)`、`ApplyRequest`、`RollbackRequest`、`IssueInput`、`SelectionInput`、`BackupInput` | `pydantic`（既有） | ≤110 |
| `backend/app/fixer/paths.py` | 路径规范化、归属校验、repo_label、符号链接 | `def resolve_repo(raw: str, settings: object) -> Path`；`def resolve_file(repo_root: Path, relative: str) -> Path`；`def resolve_backup_dir(repo_root: Path, raw: str) -> Path`；`def resolve_backup_path(backup_root: Path, relative: str) -> Path`；`def repo_label(repo_root: Path) -> str`；`def is_symlink(path: Path) -> bool` | 标准库、`app.api.security`、`app.api.settings` | ≤190 |
| `backend/app/fixer/patches.py` | link-005 补丁生成 | `def decode_text(data: bytes) -> tuple[str, str]`（返回文本与编码标记）；`def build_line_patch(line: str, line_no: int, rule_id: str, file_path: str) -> PatchDraft \| None`；`def build_patch(repo_root: Path, issue: IssueInput, *, label: str) -> Patch` | 标准库、`app.core.rules.link_check`（只读正则） | ≤230 |
| `backend/app/fixer/backup.py` | backup_id、目录布局、备份、原子写、哈希 | `def new_backup_id(base: Path) -> str`；`def backup_file(backup_root: Path, source: Path, relative: str) -> BackupRecord`；`def atomic_write(path: Path, data: bytes) -> None`；`def sha256_bytes(data: bytes) -> str` | 标准库 | ≤190 |
| `backend/app/fixer/locks.py` | 按仓库进程内串行锁 | `class RepoLockRegistry`：`acquire(self, repo_root: Path, timeout: float = 5.0) -> contextmanager`；`def registry() -> RepoLockRegistry` | 标准库 | ≤80 |
| `backend/app/fixer/audit.py` | stdout 结构化审计日志 | `def audit(action: str, *, request_id: str, repo_label: str, files: list[dict[str, object]], result: str, duration_ms: int) -> None` | 标准库、`logging` | ≤90 |
| `backend/app/fixer/service.py` | preview/apply/rollback 编排 | `def preview(repo_root: Path, issues: list[IssueInput], *, strict: bool) -> dict[str, object]`；`def apply(repo_root: Path, backup_dir: Path, selections: list[SelectionInput], *, on_stale: str, strict: bool, request_id: str) -> dict[str, object]`；`def rollback(repo_root: Path, backup_dir: Path, backup_id: str, backups: list[BackupInput], *, force: bool, strict: bool, request_id: str) -> dict[str, object]` | `app.fixer.*` | ≤280 |
| `backend/app/fixer/router.py` | 三个 POST 端点、依赖、错误映射 | `router: APIRouter`；`def get_web_settings(request: Request) -> object`；`def require_desktop(settings=Depends(get_web_settings)) -> object`；`def require_json(request: Request) -> None`；`def require_body_size(request: Request) -> None` | `fastapi`、`app.fixer.*`、运行期 `app.api.routes.ApiError` | ≤240 |

新增后端文件共 11 个（含 `__init__.py`）。

## 4.2 逐文件设计

### 4.2.1 `__init__.py`

- 只做包标记与 `router` 再导出。
- 不在包导入时加载 `app.api.*` 或 `app.core.rules.*`，避免 `app.py` 导入期循环。

### 4.2.2 `errors.py`

常量：
- `FIXER_INVALID_SELECTION`、`FIXER_BACKUP_DIR_FORBIDDEN`、`FIXER_BACKUP_PATH_FORBIDDEN`、`FIXER_STALE_PATCH`、`FIXER_FILE_UNDECODABLE`、`FIXER_ROLLBACK_CONFLICT`、`FIXER_IO_ERROR`。
- 设计补充：`UNSUPPORTED_MEDIA_TYPE`（415）、`PAYLOAD_TOO_LARGE`（413）。

`raise_fixer()`：
- 运行期导入 `app.api.routes.ApiError` 并抛出，复用 `app.py:86-88` 处理器。
- 不在模块顶层导入 `app.api.routes`，避免与 `app.py` 导入顺序耦合。

### 4.2.3 `models.py`

`Patch`：
- `patch_id`、`file_path`、`line_no`、`rule_id`、`fixable`、`old_line`、`new_line`、`diff`、`reason`。

`Selection`：
- `file_path`、`line_no`、`rule_id`、`old_line`。

`BackupRecord`：
- `file_path`、`backup_path`（相对 `backup_dir`）、`captured_at`、`after_sha256`。

`ApplyResult`：
- `repo`、`backup_id`、`applied[]`、`skipped[]`、`backups[]`。

`RollbackResult`：
- `repo`、`restored[]`、`failed[]`。

`to_dict()`：标准库 dataclass 序列化，保持 spec 6.1/6.2/6.3 字段名。

### 4.2.4 `schemas.py`

Pydantic 模型（沿用既有 `pydantic`，不新增依赖）：
- `IssueInput`：`file_path`、`line_no`、`rule_id`、`excerpt`（可选，≤200）。
- `SelectionInput`：`file_path`、`line_no`、`rule_id`、`old_line`。
- `BackupInput`：`file_path`、`backup_path`、`after_sha256`。
- `PreviewRequest`：`repo`、`issues: list[IssueInput]`（1–200）、`strict: bool=False`。
- `ApplyRequest`：`repo`、`backup_dir`、`on_stale: Literal["skip","reject"]="skip"`、`strict: bool=False`、`selections: list[SelectionInput]`（1–200）。
- `RollbackRequest`：`repo`、`backup_dir`、`backup_id`、`force: bool=False`、`strict: bool=False`、`backups: list[BackupInput]`（1–200）。

`model_config = ConfigDict(extra="ignore")`，与 `backend/app/api/schemas.py:11-17` 的风格一致。

### 4.2.5 `paths.py`

1. `resolve_repo(raw, settings)`：直接调用 `app.api.security.resolve_repo_root`；返回 `Path`。
2. `resolve_file(repo_root, relative)`：
   - 拒绝绝对路径、盘符、UNC、设备路径、`..`（复用 `security.py:31-45` 的 helper）。
   - `candidate = (repo_root / relative).resolve(strict=False)`。
   - 用 `os.path.commonpath` 比较 `repo_root` 与 `candidate`（Windows 下 `casefold`），不等 → `REPO_FORBIDDEN` 403。
   - `lstat` 为符号链接 → `FIXER_INVALID_SELECTION` 400（preview 中转为 `fixable=false`）。
3. `resolve_backup_dir(repo_root, raw)`：
   - 绝对路径、存在、目录、可写。
   - `_is_protected_system_dir` 等价校验（复用 `security.py:57-70`）。
   - 解析后必须 **不在** `repo_root` 内；否则 `FIXER_BACKUP_DIR_FORBIDDEN` 403。
   - 不自动创建目录。
4. `resolve_backup_path(backup_root, relative)`：
   - 必须是相对路径；拒绝 `..`、绝对路径。
   - `(backup_root / relative).resolve(strict=False)` 必须位于 `backup_root` 内。
   - `lstat` 为符号链接 → `FIXER_BACKUP_PATH_FORBIDDEN` 403。
5. `repo_label(repo_root)`：
   - 安全化 `root.name`（替换非字母数字/中文/短横线为 `_`）。
   - 追加 `sha256(os.path.normcase(str(root.resolve())))` 前 8 位，格式 `name-8hex`，避免同名冲突。
   - 不含盘符/分隔符/绝对路径。
6. `is_symlink(path)`：
   - 使用 `os.lstat` + `stat.S_ISLNK`，不使用 `Path.is_symlink()`（便于测试 patch `app.fixer.paths.os.lstat`）。

### 4.2.6 `patches.py`

`decode_text(data)`：
- 检测 UTF-8 BOM（`b"\xef\xbb\xbf"`），返回 `(text, "utf-8-sig")`；否则尝试 `utf-8`；失败抛解码错误（由 service 转为 `fixable=false` / skipped）。
- 仅接受 UTF-8 / UTF-8 BOM；GBK 等不做自动猜测。

`build_line_patch(line, line_no, rule_id, file_path)`：
1. `rule_id != "link-005"` → 返回 `None`（`fixable=false`，reason="非白名单规则"）。
2. 用 `INLINE_RE`（`link_check.py:21`）遍历行内 inline/image：
   - `wrapped`：匹配文本的 target 以 `<` 开头、`>` 结尾 → 跳过；
   - 拆分 `group(3)` 为 `target` 与 `title`（若存在空白 + 引号；title 原样保留）；
   - 只对 `target` 中的半角空格替换为 `%20`；
   - 记录替换后的整行。
3. 用 `DEFINITION_RE`（`link_check.py:23`）匹配 definition：
   - `group(2).strip().split()` 的第一段为 target，其余为 title；
   - 只替换 target 中的空格，title 原样保留；
   - 替换后重建 `[id]: target title`。
4. 无任何命中 → `None`（reason="定位不到 link-005 目标"）。
5. 返回整行 `old_line` / `new_line`；同一行多个链接一次性处理。

`build_patch(repo_root, issue, label)`：
1. `resolve_file` 校验路径；符号链接 → `fixable=false`。
2. 读取 bytes、`decode_text`；失败 → `fixable=false`，reason="文件无法按 UTF-8 解码"。
3. `line_no` 越界（<1 或 >行数）→ `fixable=false`。
4. 取目标行，调用 `build_line_patch`。
5. 生成 `patch_id = sha256(f"{label}|{file_path}|{line_no}|{rule_id}|{old_line}|{new_line}")[:16]`。
6. 生成 unified diff：
   - `difflib.unified_diff([old_line], [new_line], fromfile=f"{file_path}:{line_no}", tofile=f"{file_path}:{line_no}", lineterm="")`；
   - 前缀 `---`/`+++`/`@@` 保留，前端按行着色。
7. 返回 `Patch`。

### 4.2.7 `backup.py`

`new_backup_id(base)`：
- `datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:18]` → `YYYYMMDD-HHMMSS-fff`。
- 若 `base/backup_id` 已存在，追加 `-<6位hex>`；仍冲突追加 `-<序号>`。

`backup_file(backup_root, source, relative)`：
- 目标：`backup_root / relative`（`relative` 已含 `backup_id/repo_label/...`）。
- 创建父目录；`shutil.copy2(source, target)` 保留字节、mtime、权限。
- 计算 `sha256_file(target)` 作为校验；返回 `BackupRecord`。
- 备份失败抛 `FIXER_IO_ERROR`（请求级）或由 service 转为单文件 skipped。

`atomic_write(path, data)`：
- 同目录临时文件 `.name.repoguard.tmp`；
- 写入 bytes、`flush`/`fsync`（可用 `os.fsync`）；
- `os.replace(tmp, path)`；
- 保留原权限：写入前 `os.stat(path).st_mode`，`os.chmod` 恢复；
- 失败删除 tmp 并抛 `OSError`。

### 4.2.8 `locks.py`

- `RepoLockRegistry`：`dict[str, threading.Lock]` + 全局 `threading.Lock` 保护创建。
- 键：`os.path.normcase(str(repo_root.resolve()))`。
- `acquire(repo_root, timeout=5.0)`：
  - `lock.acquire(timeout=5.0)`；
  - 超时抛 `LockTimeout`（fixer 内部异常）→ router 映射 503 / `FIXER_IO_ERROR`；
  - 释放时 `lock.release()`。
- 不做跨进程锁；单实例桌面进程内有效。
- 锁粒度：同一仓库的 apply/rollback；preview 不获取锁（只读）。

### 4.2.9 `audit.py`

- `LOGGER = logging.getLogger("repoguard.fixer")`。
- `audit()` 组装字典并 `LOGGER.info(json.dumps(record, ensure_ascii=False))`。
- 字段：`time`（ISO 8601 UTC）、`request_id`、`repo_label`、`action`、`files[]`（相对路径）、`rule_id`、`old_line`/`new_line` 摘要（≤200 字符）、`backup_path`（相对）、`result`、`duration_ms`。
- 不新增 handler、不写文件、不做轮转；由运行环境的 logging 配置输出到 stdout（与 `app.py:81` 中间件日志同一出口）。
- 禁止绝对路径、全文、密钥、webhook payload。

### 4.2.10 `service.py`

`preview()`：
- 逐条 `build_patch`；收集 `fixable=true/false`。
- `strict=true` 且存在不可解码 → 抛 `FIXER_FILE_UNDECODABLE` 422。
- 不落盘、不备份、不改仓库。

`apply()`：
1. 校验 `selections` 非空、≤200、无重复（`file_path+line_no+rule_id+old_line`）。
2. 对每条 selection：白名单、`resolve_file`、符号链接、读取/解码、行号、重建补丁、比对 `old_line`。
3. 分类：
   - 非白名单/缺字段/无法定位 → 400 `FIXER_INVALID_SELECTION`（请求级）。
   - 陈旧 → `skipped`；`on_stale="reject"` → 409 `FIXER_STALE_PATCH`。
   - 不可解码 → `skipped`；`strict=true` → 422 `FIXER_FILE_UNDECODABLE`。
4. 按 `file_path` 分组；每文件只备份一次；补丁按 `line_no` 升序。
5. 获取仓库锁（5 秒）；超时 → 503 `FIXER_IO_ERROR`。
6. 备份每个待写文件；失败 → 该文件 skipped。
7. 逐文件：重读当前 bytes、再次校验每行 `old_line`、构造新内容、`atomic_write`；成功后计算 `after_sha256`。
8. 审计日志；返回 `ApplyResult`。
9. 中途失败：已成功文件不回滚；已备份保留；失败文件记 skipped。

`rollback()`：
1. 校验 `backup_dir`、`backup_id`、每个 `backup_path` 归属。
2. 获取仓库锁（5 秒）。
3. 逐文件：备份存在、读取 bytes、计算目标当前 sha256。
4. `after_sha256` 不一致：`force=false` → failed；`strict=true` → 409 `FIXER_ROLLBACK_CONFLICT`；`force=true` → 覆盖并在 `restored` 中标注。
5. 原子覆盖、保留权限；审计日志。

### 4.2.11 `router.py`

依赖：
- `get_web_settings(request)`：`request.app.state.settings`；缺失 → 500 `INTERNAL_ERROR`。
- `require_desktop(settings)`：`not desktop_mode` → 404 `NOT_FOUND`（与 `app.py:104-115` 的 404 一致）。
- `require_json(request)`：`Content-Type` 以 `application/json` 开头，否则 415 `UNSUPPORTED_MEDIA_TYPE`。
- `require_body_size(request)`：`Content-Length > 2*1024*1024` → 413 `PAYLOAD_TOO_LARGE`；缺失 `Content-Length` 时由 Pydantic/服务器限制兜底。

端点：
- `@router.post("/preview")` → `service.preview`
- `@router.post("/apply")` → `service.apply`
- `@router.post("/rollback")` → `service.rollback`
- 全部 `async def`；I/O 经 `asyncio.to_thread`。
- 返回 `JSONResponse`（`Content-Type: application/json; charset=utf-8`）。

---

# 五、接口契约

## 5.1 依赖链与边界

| 场景 | 行为 | 错误码 |
|---|---|---|
| 非桌面模式 | 404 | `NOT_FOUND` |
| GET/ PUT 等非 POST | 405 | `METHOD_NOT_ALLOWED`（`app.py:104-115`） |
| `Content-Type` 非 JSON | 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 请求体 > 2 MB | 413 | `PAYLOAD_TOO_LARGE` |
| `issues`/`selections`/`backups` > 200 | 422 | `VALIDATION_ERROR` |
| 字段缺失/类型错误 | 422 | `VALIDATION_ERROR` |
| `repo` 越界/不存在 | 403/404/400 | 复用 `REPO_*` |

## 5.2 `POST /api/fixer/preview`

请求：`PreviewRequest`（`repo`、`issues[]`、`strict`）。
响应：
```json
{
  "repo": "demo-repo-3f2a1c9b",
  "patches": [
    {
      "patch_id": "5a1c0f9e2b7d4c31",
      "file_path": "docs/lab02.md",
      "line_no": 13,
      "rule_id": "link-005",
      "fixable": true,
      "old_line": "[x](./lab 02.md)",
      "new_line": "[x](./lab%2002.md)",
      "diff": "--- docs/lab02.md:13\n+++ docs/lab02.md:13\n@@ -1 +1 @@\n-[x](./lab 02.md)\n+[x](./lab%2002.md)",
      "reason": null
    }
  ]
}
```
- `repo` 为 `repo_label`，不含绝对路径。
- `patch_id` 仅本次响应有效。
- 不可修复项只返回 `fixable=false` + `reason`。

## 5.3 `POST /api/fixer/apply`

请求：`ApplyRequest`（`repo`、`backup_dir`、`selections[]`、`on_stale`、`strict`）。
响应：
```json
{
  "repo": "demo-repo-3f2a1c9b",
  "backup_id": "20261117-230512-123",
  "applied": [
    {
      "patch_id": "5a1c0f9e2b7d4c31",
      "file_path": "docs/lab02.md",
      "line_no": 13,
      "after_sha256": "..."
    }
  ],
  "skipped": [
    {
      "file_path": "docs/other.md",
      "rule_id": "link-005",
      "reason": "文件内容已变化，补丁已过期"
    }
  ],
  "backups": [
    {
      "file_path": "docs/lab02.md",
      "backup_path": "20261117-230512-123/demo-repo-3f2a1c9b/docs/lab02.md",
      "captured_at": "2026-11-17T23:05:12Z"
    }
  ]
}
```
- 不返回 `backup_dir` 绝对路径。
- `selections` 缺失定位字段 → 400 `FIXER_INVALID_SELECTION`。

## 5.4 `POST /api/fixer/rollback`

请求：`RollbackRequest`（`repo`、`backup_dir`、`backup_id`、`backups[]`、`force`、`strict`）。
响应：
```json
{
  "repo": "demo-repo-3f2a1c9b",
  "restored": [{ "file_path": "docs/lab02.md" }],
  "failed": [{ "file_path": "docs/other.md", "reason": "备份原件缺失" }]
}
```
- `backup_path` 越界 → 403 `FIXER_BACKUP_PATH_FORBIDDEN`。
- 手工修改冲突：默认 failed；`strict=true` → 409 `FIXER_ROLLBACK_CONFLICT`。

## 5.5 错误码 HTTP 映射

| code | HTTP | 来源 |
|---|---|---|
| `FIXER_INVALID_SELECTION` | 400 | 设计 |
| `FIXER_BACKUP_DIR_FORBIDDEN` | 403 | 设计 |
| `FIXER_BACKUP_PATH_FORBIDDEN` | 403 | 设计 |
| `FIXER_STALE_PATCH` | 409 | 设计 |
| `FIXER_FILE_UNDECODABLE` | 422 | 设计 |
| `FIXER_ROLLBACK_CONFLICT` | 409 | 设计 |
| `FIXER_IO_ERROR` | 500 / 503（锁超时） | 设计（冲突见第十三节） |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | design 补充 |
| `PAYLOAD_TOO_LARGE` | 413 | design 补充 |
| `REPO_FORBIDDEN` / `REPO_NOT_FOUND` / `INVALID_REPO_PATH` | 403/404/400 | 复用 |
| `VALIDATION_ERROR` | 422 | 复用 |
| `METHOD_NOT_ALLOWED` | 405 | 复用 |
| `NOT_FOUND` | 404 | 复用（非桌面模式） |
| `INTERNAL_ERROR` | 500 | 复用兜底 |

## 5.6 单条失败与请求级错误

- 默认：陈旧、不可解码、不可写、备份失败 → `skipped` / `failed`，HTTP 200。
- `on_stale="reject"` → 409，整请求不写。
- `strict=true` 且不可解码 → 422，整请求不写。
- `strict=true` 且回滚冲突 → 409，整请求不覆盖。
- `FIXER_INVALID_SELECTION` / `FIXER_BACKUP_*` / 415 / 413 → 请求级，整请求不写。

---

# 六、备份目录布局与命名

## 6.1 布局

```text
<backup_dir>/
  <backup_id>/
    <repo_label>/
      <仓库内相对路径>
```

示例：
```text
D:\RepoGuardBackups\
  20261117-230512-123\
    demo-repo-3f2a1c9b\
      docs\lab02.md
      README.md
```

## 6.2 命名规则

- `backup_id = YYYYMMDD-HHMMSS-fff`（本地时间，毫秒）。
- 同毫秒冲突：追加 `-<6位十六进制随机后缀>`；仍冲突：追加 `-<序号>`。
- `repo_label = <安全化目录名>-<8位哈希>`；哈希基于 `normcase(resolve(repo_root))`。
- `backup_path` 为相对 `backup_dir` 的路径，使用 `/` 分隔（响应中统一 `as_posix()`）。
- 备份文件保留原字节、mtime、权限（`shutil.copy2`）。
- 不写备份清单文件；清单随 apply 响应返回，前端内存暂存。

## 6.3 安全校验

1. `backup_dir`：绝对路径、存在、目录、可写、非系统敏感目录、解析后不在仓库根内。
2. `backup_path`：相对路径、无 `..`、解析后在 `backup_dir/backup_id` 内、`lstat` 非符号链接。
3. `file_path`：相对路径、解析后在仓库根内、`lstat` 非符号链接。
4. Windows 路径比较使用 `casefold` + `commonpath`，不用字符串 `startswith`。

---

# 七、前端设计

## 7.1 文件与职责

| 文件 | 动作 | 职责 | 行数预算 |
|---|---|---|---|
| `frontend/src/api/fixer.js` | 新增 | `previewFix` / `applyFix` / `rollbackFix` 三个 POST；`FIXER_MESSAGES` 错误映射 | ≤90 |
| `frontend/src/components/FixPreviewDialog.vue` | 新增 | 触发按钮 + 弹窗 + 补丁列表 + diff 预览 + 备份目录选择 + apply/rollback | ≤260 |
| `frontend/src/views/IssuesView.vue` | 最小修改 | `#detail` 插槽挂载 `<FixPreviewDialog :issue="row" :repo-id="repoId" @applied="load" />` | 368 → ≤383 |

## 7.2 `api/fixer.js`

```js
export function previewFix({ repo, issues, strict, signal } = {})
export function applyFix({ repo, backupDir, selections, onStale, strict, signal } = {})
export function rollbackFix({ repo, backupDir, backupId, backups, force, strict, signal } = {})
```
- 全部调用 `requestJson('/api/fixer/...', { method: 'POST', body, signal, timeoutMs: 60000 })`。
- `FIXER_MESSAGES` 补充 `FIXER_INVALID_SELECTION`、`FIXER_BACKUP_DIR_FORBIDDEN`、`FIXER_BACKUP_PATH_FORBIDDEN`、`FIXER_STALE_PATCH`、`FIXER_FILE_UNDECODABLE`、`FIXER_ROLLBACK_CONFLICT`、`FIXER_IO_ERROR`、`UNSUPPORTED_MEDIA_TYPE`、`PAYLOAD_TOO_LARGE`。
- 不修改 `client.js`。

## 7.3 `FixPreviewDialog.vue`

Props：
- `issue: Object`（`file_path`、`line_no`、`rule_id`、`excerpt`）。
- `repoId: String`。

Emits：
- `applied`：apply 成功后通知父组件触发复扫。

State：
- `open`、`loading`、`error`、`preview`、`selectedIds`、`backupDir`、`applyResult`、`rollbackResult`、`fixerAvailable`。

行为：
1. 仅当 `issue.rule_id === 'link-005'` 且 `fixerAvailable` 时渲染"查看修复"按钮。
2. `fixerAvailable = Boolean(window.repoguard?.pickDirectory)`；非桌面模式不渲染按钮，并显示"修复功能仅在桌面版可用"。
3. 点击按钮 → `previewFix`；弹窗展示 `old_line`/`new_line`/`diff`。
4. 补丁列表勾选 → `selectedIds`。
5. "选择备份目录" → `window.repoguard.pickDirectory()`；取消（null）停留。
6. "确认写入" → `applyFix`；展示 `applied`/`skipped`/`backups`；emit `applied`。
7. 回滚按钮 → `rollbackFix`（使用本次 apply 的 `backup_id` + `backups`）；展示 `restored`/`failed`。
8. 错误用 `ApiClientError` 的 `code/message/detail/requestId` 展示。

## 7.4 diff 渲染

- 后端返回 unified diff 文本。
- 前端 `split('\n')` 生成行数组；模板 `v-for` 渲染：
  - `+` 开头 → `diff-line--add`（绿色文字 + "新增" 文字标识）；
  - `-` 开头 → `diff-line--del`（红色文字 + "删除" 文字标识）；
  - `@@` 开头 → `diff-line--hunk`；
  - 其他 → 默认。
- 使用 `<pre>` + 文本插值；**禁止 `v-html`**。
- 不引入 diff 渲染库。

## 7.5 复扫与节流

- apply 成功后 `emit('applied')`；`IssuesView` 调用既有的 `load()` 并带一次性 `refresh=1`。
- dashboard TTL 60 秒、`refresh=1` 10 秒节流；被节流时展示"快照刷新过于频繁，将在 60 秒内自动更新"。
- 不修改 dashboard 接口。

## 7.6 行数预算

- `IssuesView.vue` 当前 368 行；新增 import 2 行 + 模板 3 行，控制在 383 行以内（≤400）。
- `FixPreviewDialog.vue` ≤260；`api/fixer.js` ≤90。
- 不修改 `frontend/package.json` / lock。

---

# 八、桌面壳

- 复用 `desktop/main/main.js:15-23` 的 `repoguard:pick-directory`；复用 `desktop/main/preload.js:5-8` 的 `window.repoguard.pickDirectory()`。
- 不新增 IPC；现有标题"选择要巡检的仓库文件夹"不改，前端在备份场景提示"请选择仓库之外的备份目录"。
- 桌面壳本轮无需改动；若后续需要区分标题，只允许在 `main.js` 增加可选参数，不新增 IPC 名称。
- 非桌面模式：`window.repoguard?.pickDirectory` 不存在 → 前端不显示修复入口，并提示降级。
- 后端通过 `WebSettings.desktop_mode` 判定；非桌面模式 fixer 三个端点 404。

---

# 九、测试设计

## 9.1 测试文件与基础设施

- 新增 `backend/tests/test_fixer.py`。
- 统一 `python -m unittest`；不引入其他测试运行器。
- API 级使用 `backend/tests/webhook_helpers.py:124-145` 的 `WebhookASGIClient`：
  - `client = WebhookASGIClient(app)`；
  - `client.post("/api/fixer/preview", json={...})`；
  - 不启动真实端口、不使用框架内置同步测试客户端。
- 文件系统用例使用 `tempfile.TemporaryDirectory()`：
  - 临时仓库：`tmp/repo/docs/lab.md`；
  - 临时备份目录：`tmp/backups`（仓库外）；
  - `addCleanup` 清理。
- `with no_network():` 包裹 API 用例（`webhook_helpers.py:147-152`）。
- app 创建：`create_app(WebSettings(desktop_mode=True, allowed_repo_roots=(tmp,), default_repo="repo", static_dir=...))`；测试传仓库绝对路径。

## 9.2 14 条新增用例

| 编号 | 方法 | 类型 | 覆盖 |
|---|---|---|---|
| T-F01 | `test_preview_link005_inline_image_definition` | ASGI | inline/image/definition 均生成 `%20`，definition title 不变 |
| T-F02 | `test_preview_angle_wrapped_and_missing_target_not_fixable` | ASGI | 尖括号、定位不到、行号越界 → `fixable=false` |
| T-F03 | `test_preview_non_whitelisted_rule_not_fixable` | ASGI | 非 link-005 → `fixable=false` |
| T-F04 | `test_preview_rejects_file_path_outside_repo` | ASGI | `..`/绝对路径 → 拒绝 |
| T-F05 | `test_preview_rejects_symlink_escape` | FS + mock | mock `os.lstat` 返回符号链接 → 拒绝 |
| T-F06 | `test_backup_dir_inside_repo_rejected` | ASGI | 备份目录在仓库内 → 403 |
| T-F07 | `test_apply_backs_up_before_write_and_bytes_match` | ASGI | 先备份后写入，字节一致 |
| T-F08 | `test_apply_stale_old_line_skipped` | ASGI | 旧行变化 → skipped |
| T-F09 | `test_apply_multi_patch_same_file_backs_up_once` | FS | 同文件多补丁只备份一次 |
| T-F10 | `test_apply_same_line_multiple_links_single_patch` | FS | 同一行多链接合并为一个补丁 |
| T-F11 | `test_rollback_restores_original_bytes` | ASGI | 回滚字节一致 |
| T-F12 | `test_rollback_backup_path_escape_rejected` | ASGI | backup_path 越界 → 403 |
| T-F13 | `test_rollback_detects_manual_modification` | ASGI | 手工修改 → 默认 failed |
| T-F14 | `test_apply_undecodable_and_unwritable_skipped` | FS | GBK/二进制/只读 → skipped |

其中 T-F01、T-F03、T-F04、T-F06、T-F08、T-F11 至少 6 条通过 ASGI 调用三个 POST 端点。

## 9.3 符号链接 mock 设计

- `paths.is_symlink()` 使用 `os.lstat` + `stat.S_ISLNK`。
- 测试：`with patch("app.fixer.paths.os.lstat", return_value=FakeStat(st_mode=stat.S_IFLNK))`。
- 不依赖真实 `os.symlink`，不增加 skipped。
- 目标文件归属校验单独用真实临时目录验证。

## 9.4 基线与回归

- 既有：`Ran 452 tests` → `OK (skipped=4)`。
- 新增 14 条：`Ran 466 tests` → `OK (skipped=4)`（462 passed / 0 failed / 4 skipped）。
- 新增用例不得增加 skip。
- 既有 2 条 `test_repo_walk` 符号链接用例可能 failed/skipped 漂移，单列不修。
- 命令：`cd backend && <uv CPython 3.11.15> -m unittest discover -s tests -t .`。
- 单跑：`python -m unittest tests.test_fixer`。

## 9.5 冻结与前端验收

- 15 项 SHA-256 一致（13 冻结 + requirements + static）。
- `scripts/verify_frozen_hashes.py:73-99` 的 `app.py` 期望增量需调整（见第十三节）。
- 29 个既有测试文件零改动。
- 前端：`npm ci` + `npm run build`；0 `v-html`；请求只经 `api/fixer.js`；无 `fetch(` / `/api/` 字面路径。

---

# 十、冻结与不纳入

## 10.1 零改动

- `backend/app/core/rules/**`（13 个冻结文件）
- `backend/app/api/routes.py` 只读巡检契约
- `backend/app/api/static/index.html`
- `backend/app/dashboard/**` 既有 GET 路由（fixer 不改其代码）
- `backend/requirements.txt`
- `frontend/package.json` / `package-lock.json`
- `desktop/package.json` / `package-lock.json`
- 29 个既有测试文件
- 4 份既有使用文档
- `deploy/` 22 个产物（不改 nginx）
- 15 项哈希

## 10.2 允许改动

- `backend/app/api/app.py`：fixer 自身 +2/-0（1 import + 1 include_router）。
- `backend/app/fixer/**`：新增 11 个文件。
- `backend/tests/test_fixer.py`：新增。
- `frontend/src/api/fixer.js`：新增。
- `frontend/src/components/FixPreviewDialog.vue`：新增。
- `frontend/src/views/IssuesView.vue`：最小修改（≤15 行）。
- `scripts/verify_frozen_hashes.py`：仅调整 `app.py` 期望增量（见第十三节）。
- `docs/fixer_usage.md`：后续交付。

## 10.3 不纳入

- 其他规则修复、一键全改、git 自动提交。
- 历史备份列表页 / 查询接口、备份自动清理。
- 服务端定时自动修复。
- 非桌面模式的写能力。
- nginx / 公网暴露与鉴权体系。

---

# 十一、假设与偏差登记

| 编号 | 事项 | 影响 | 设计处理 |
|---|---|---|---|
| A-01 | `app.py` 相对 `app.py.orig` 实测 +8/-1（存量 storage/static mount/dashboard）；fixer 后 +10/-1 | 实测存量 +8/-1；fixer 自身 +2/-0 | **已对齐 spec**：采纳方案 A（stage6 快照基线 +2/-0），stage5 存量 +8/-1 不计入 fixer 增量（§13.1） |
| A-02 | 锁等待超时定稿 503 / `FIXER_IO_ERROR`，spec 表为 500 | spec 已改为 503 | **已对齐 spec**：锁等待超时 503 / `FIXER_IO_ERROR`；500 仅保留给 `INTERNAL_ERROR`（§13.2） |
| A-03 | 415 / 413 无既有错误码 | spec 7.2 已补两码 | **已对齐 spec**：415 `UNSUPPORTED_MEDIA_TYPE`、413 `PAYLOAD_TOO_LARGE` 已进入 7.2（§13.3） |
| A-04 | `dashboard/router.py:296-314` 存量 `check-repo` 返回绝对路径 | 与脱敏口径冲突 | fixer 不依赖、不修；登记为存量偏差 |
| A-05 | `repo_label` 使用 `name-8hex` | spec 8.3 只写"相对名/标识" | 短哈希用于避免同名冲突；不回传绝对路径 |
| A-06 | `IssuesView.vue` 已 368 行 | 增加入口可能超 400 行 | 触发按钮放入 `FixPreviewDialog`，IssuesView 仅加 import + 一行模板 |
| A-07 | `client.js` 默认 45s | apply 可能耗时 | `api/fixer.js` 显式 60s，不改 `client.js` |
| A-08 | desktop_mode 下 `repo` 必须绝对路径（`security.py:110-117`） | 前端需传当前仓库绝对路径 | 设计明确桌面模式传绝对路径；非桌面 404 |
| A-09 | `link_check.extract_links()` 的 `raw` 截断 60、无列偏移 | 不能直接用于替换 | 用 `INLINE_RE`/`DEFINITION_RE` 重新定位；`extract_links` 仅做 kind/wrapped 判定 |
| A-10 | `link_check` 的 definition target 解析丢弃 title（`link_check.py:121-137`） | 修复需保留 title | `patches.py` 自行拆分 target/title，测试锁定 |
| A-11 | 备份目录必须已存在（不自动创建） | 用户需先建目录 | service 校验存在/可写，否则 403 |
| A-12 | 审计日志 stdout，无独立文件/轮转 | 依赖运行环境日志收集 | 使用 `logging.getLogger("repoguard.fixer")`，与 `app.py:81` 同出口 |
| A-13 | 无历史备份列表页，前端刷新后不可回滚 | 用户需自行记录 | 仅本次会话内存清单；文档说明 |

---

# 十二、验收映射

| spec 验收 | design 落点 |
|---|---|
| 1 冻结/GET/依赖零改动 | 10.1；9.5；13 节 |
| 2 preview link-005 与脱敏 | 4.2.6；5.2；6.2 |
| 3 apply 完整定位/备份/旧行/409 | 4.2.10；5.3；5.6；9.2 |
| 4 rollback 还原/越界/手工修改 | 4.2.10；5.4；6.3；9.2 |
| 5 前端入口/diff/复扫 | 7.1–7.6；8 |
| 6 452/466 skipped=4 + 构建 | 9.4；9.5 |
| 7 不一键全改/不 git/无历史页/不自动清理 | 1.2；10.3；8.4（spec） |
| 8 桌面 GUI | 7.3；8；9.2（手工验收部分） |

---

# 十三、与 spec 口径对齐记录（已闭合）

1. **S-01 `app.py` 增量口径（已闭合）**
   - 背景：spec 9.4 原写 `app.py` 期望 `+4/-0`。
   - 实测：`app.py.orig` 187 行 → 当前 194 行，`added=8 removed=1`；fixer 再 +2/-0 后为 `+10/-1`（196 行）。
   - **采纳结论：方案 A 已采纳。** 在 tasks 阶段生成 `.codeartsdoer/evidence/stage6/app.py.stage6.orig`（当前 194 行快照），`verify_frozen_hashes.py` 基线切到该文件，期望 **相对 stage6 快照 +2/-0**；阶段 5 的 `app.py.orig` 与 15 项哈希证据保留不动。
   - 未采纳备选：保持 `app.py.orig` 187 行基线、期望改为 `+10/-1`。
   - spec 落点：9.4、13.2（stage5 存量 +8/-1 作为既有偏差登记，不计入 fixer 增量）。

2. **S-02 锁等待超时状态码（已闭合）**
   - 背景：spec 7.2 原将 `FIXER_IO_ERROR` 定为 500。
   - design 定稿：等待超时 5 秒，返回 **503 / `FIXER_IO_ERROR`**。
   - **采纳结论：已按 503 对齐。** spec 7.2 将 `FIXER_IO_ERROR` 改为 503（锁等待超时 5 秒）；500 仅保留给 `INTERNAL_ERROR` 兜底。
   - spec 落点：7.2、4.9。

3. **S-03 415 / 413 错误码（已闭合）**
   - 背景：spec 6.4 要求非 JSON 415、2MB 上限；7.2 原无对应错误码。
   - **采纳结论：已补入 spec 7.2。** 新增 `UNSUPPORTED_MEDIA_TYPE`（415，非 JSON）、`PAYLOAD_TOO_LARGE`（413，请求体超 2MB）；spec 6.4 的上限描述与错误码对齐。
   - spec 落点：6.4、7.2。

4. **S-04 桌面模式 `repo` 入参（已闭合）**
   - 背景：spec 3.1 原允许“标识/相对名”；`security.py:110-117` 在 desktop_mode 下要求绝对路径。
   - **采纳结论：已澄清。** spec 3.1 已写明“桌面模式下 `repo` 必须为仓库绝对路径（仅请求内部使用，不入响应）；响应统一返回 `repo_label`”。
   - spec 落点：3.1。

5. **S-05 `repo_label` 短哈希（已闭合）**
   - 背景：spec 8.3 原只写“仓库相对名 / dashboard 仓库标识”；design 使用 `name-8hex` 避免同名冲突。
   - **采纳结论：已允许。** spec 8.3 允许 `repo_label` 为“相对名 + 8 位短哈希（`name-8hex`）”，仍禁止绝对路径。
   - spec 落点：8.3。

6. **S-06 `FixPreviewDialog` 承载触发按钮（已闭合）**
   - 背景：spec 10.2 原只写“diff 预览弹窗组件”；design 将触发按钮放入同一组件，以控制 `IssuesView.vue` 行数。
   - **采纳结论：已澄清。** spec 10.2 已补“查看修复触发按钮可并入 `FixPreviewDialog.vue`，`IssuesView` 仅做 import 与模板挂载，不承载按钮/弹窗逻辑”。
   - spec 落点：10.2。

**结论：以上六项均已闭合，design 与 spec 无剩余未闭合口径冲突。**

以上 1–3 项会影响验收数字/错误码，必须在 tasks 前回 spec；4–6 为口径澄清，不阻塞实现。
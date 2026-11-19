# 修复辅助层（fixer）需求规格 spec

> 本规格是对既有规则引擎、Web API、只读看板三份"只读"规格的**补充例外**。只读引擎的代码与巡检结论不变；本层只在用户逐条确认后，对极少数零风险、纯机械的问题落地改动。
>
> 修订：2026-11-17。按 spec 核对结论闭合 P0-01～P0-06 与 P1/P2 处置口径；本轮只改规格，不写实现代码。

## 1 概述

### 1.1 背景
既有规则引擎、Web API、看板均为只读，规格明确禁止改写、移动、删除、重命名仓库文件。本阶段在其之外新增独立"修复辅助层"（fixer），仅对白名单内可机械修复的问题，提供"先预览 diff、先备份原件、用户逐条确认后才写入"的能力，不改变只读引擎给出的问题结论。

### 1.2 目标
- 对白名单内可机械修复的问题，生成旧行/新行对照与 unified diff，供用户确认。
- 写入前把被改文件原件备份到用户选择的仓库外目录。
- 确认后仅应用本次勾选的补丁，并提供按本次备份清单回滚的能力。
- 白名单之外的问题维持只读建议，不生成补丁、不写入文件。
- 所有写能力只在桌面单机模式下可用；生产 Web 不暴露 fixer。

### 1.3 范围
- 新增后端包 `app/fixer/`：补丁生成、备份、应用、回滚、审计日志。
- 新增三个 POST 接口，挂载在 `/api/fixer` 前缀下，与既有只读看板路由分离；**运行期仅在 `desktop_mode=True` 时可用**（非桌面模式所有端点 404）。
- 前端问题明细页：可修复条目出现"查看修复"入口；diff 预览弹窗（旧行红 / 新行绿）；勾选条目、选择备份目录、确认写入、写入后复扫。
- 新增前端 `api/fixer.js`（POST 封装）与 `FixPreviewDialog.vue`；`IssuesView.vue` 增加入口与弹窗挂载。
- 桌面壳**复用既有** `window.repoguard.pickDirectory()` IPC，不新增目录选择 IPC。
- 非桌面模式（纯浏览器 / Vite dev）无 preload，备份目录选择不可用，fixer 降级为不可用并提示。
- 本轮不做历史备份列表页；回滚清单仅由前端在本次会话内存中暂存。

### 1.4 职责边界
1. 规则引擎 `core/rules/` 保持只读，不改其源码与巡检结论；fixer 不调用引擎内部写路径。
2. 既有只读看板接口（GET）行为不变；fixer 是独立新路由，且仅桌面模式注册。
3. 本层不做"一键全改"：每条补丁必须用户在 diff 预览后单独勾选确认。
4. 不做 git 自动提交，不改动版本控制状态。
5. 非白名单规则一律 `fixable=false`，只返回原有建议，不生成补丁。
6. 备份与回滚产物写入用户指定的仓库外目录，不写入被巡检仓库内部。
7. 所有 `file_path`、`backup_path` 必须经过规范化与归属校验；越界拒绝。
8. 对外响应、日志不出现本机绝对路径；绝对路径仅存服务端内部。

### 1.5 与既有只读规格的关系

| 既有条款 | fixer 的处理 |
|---|---|
| `rules_engine/spec.md`：引擎只读、结论唯一来源 | `core/rules/` 与 13 个冻结文件零改动；fixer 不重写规则，只读复用链接解析口径 |
| `web_api/spec.md` 1.4：Web 层不负责自动修复、不得写仓库 | 既有 Web 层仍不写；写动作只在独立 `app/fixer/` 层，且仅桌面模式注册 |
| `web_api/spec.md` 5.1/6.1：输出脱敏、禁止绝对路径 | fixer 响应只返回仓库标识与相对路径；绝对路径仅内部使用 |
| `dashboard_deploy/spec.md` 1.4：看板只读、禁止 POST/PUT/DELETE | 既有 dashboard GET 路由不变；fixer 独立 POST，桌面模式可用，非桌面 404 |
| `dashboard_deploy/spec.md` 7.7：`app.py` 挂载增量 ≤2 行 | 阶段 5 的 +2 行基线保留；本轮允许再 +2 行（1 import + 1 include_router）并在冻结清单登记 |
| `dashboard_deploy/spec.md`：生产只读、不上云 | fixer 不经 nginx/公网；生产 Web 不注册 fixer，无新增部署产物 |

## 2 角色与流程

### 2.1 角色
巡检使用者（学生 / 开发者），在 Electron 桌面壳内操作。

### 2.2 桌面模式流程
1. 看板加载问题明细列表；前端按 `rule_id` 白名单（仅 `link-005`）显示"查看修复"入口。
2. 对白名单条目点击"查看修复"，前端调用 preview 接口；后端 dry-run 生成补丁与 diff，不落盘。
3. 用户在弹窗查看旧行（红）/ 新行（绿），勾选本次要应用的条目。
4. 用户点击"选择备份目录"，前端调用既有 `window.repoguard.pickDirectory()`；所选目录必须位于被巡检仓库之外。
5. 确认写入：后端重新生成并校验补丁、备份被改文件原件，再逐文件原子写入；返回应用 / 跳过清单与备份清单。
6. 写入完成后前端触发复扫刷新；如需撤销，按本次备份清单调用回滚接口还原。

### 2.3 非桌面模式（降级）
- 前端检测 `window.repoguard?.pickDirectory` 是否存在；不存在时不显示"查看修复"入口，并提示"修复功能仅在桌面版可用"。
- 后端在非 `desktop_mode` 时 `/api/fixer/*` 所有端点直接返回 404（由端点依赖校验），不提供替代的路径输入入口。
- 纯浏览器模式不提供任何写能力，既有看板只读行为不变。

### 2.4 备份目录选择
- 复用既有 `repoguard:pick-directory` IPC（`desktop/main/main.js:16-23`、`desktop/main/preload.js:6-8`），不新增目录选择 IPC。
- 现有 IPC 标题为"选择要巡检的仓库文件夹"；备份场景由前端提示"请选择仓库之外的备份目录"，IPC 本身不改标题。
- 用户取消选择则返回 `null`，前端停留，不调用 apply。
- 备份目录由服务端强校验：必须存在、可写、不是系统敏感目录、解析后位于仓库根之外。

### 2.5 写入后复扫
- dashboard 快照 TTL 为 60 秒，`refresh=1` 受 10 秒节流限制。
- apply 成功后前端主动请求一次强制刷新；若被节流，提示"快照刷新过于频繁，将在 60 秒内自动更新"。
- 不修改 dashboard 只读接口行为；fixer 不写 dashboard 缓存文件。

## 3 输入与路径校验

### 3.1 输入
- 仓库定位：`repo`。桌面模式下 `repo` 可为仓库绝对路径，或仓库标识（白名单根目录目录名 / 默认仓库名，与看板仓库标识同口径）；后端先把标识映射到对应白名单根目录，未命中再按绝对路径校验。解析结果仅请求内部使用，不入响应；响应统一返回 `repo_label`，不回传绝对路径。非桌面模式 fixer 不可用，不存在标识/相对名解析。
- 问题条目：`file_path`、`line_no`、`rule_id`、`excerpt`（仅作展示/提示，不作为定位依据）。
- 备份目录绝对路径：`backup_dir`（apply / rollback 请求内部使用，不回传响应）。
- 本次勾选的补丁定位：`selections`，每项必须带完整定位。
- 回滚清单：`backup_id` + `backups[]`（凭本次 apply 响应，前端内存暂存）。

### 3.2 路径规范化与归属
1. `repo` 先按标识在 `allowed_repo_roots` / `default_repo` 中映射根目录；未命中再经既有 `resolve_repo_root()` / 桌面模式等价校验（绝对路径、敏感目录、存在性、归属），解析结果仅内部使用；失败返回既有仓库错误码。
2. 所有 `file_path` 必须是仓库内相对路径；规范化后必须位于仓库根内。绝对路径、盘符、UNC、设备路径、`..` 段一律拒绝。
3. `backup_dir` 规范化后必须位于仓库根之外；位于仓库内、系统敏感目录、不存在或不可写一律拒绝。
4. `backup_path` 必须是相对路径，规范化后必须位于本次 `backup_dir/backup_id` 之内；绝对路径、`..`、符号链接逃逸一律拒绝。
5. `backup_id` 由服务端生成并在响应返回；不接受客户端自定义。
6. 所有归属校验使用解析后的真实路径比较（Windows 下大小写不敏感），禁止字符串前缀比较。

### 3.3 符号链接与 TOCTOU
- 目标文件 `lstat` 为符号链接时，直接拒绝（`fixable=false` / 跳过）。
- 目标文件解析后必须仍在仓库根内；指向仓库外的链接拒绝。
- 备份前、写入前各校验一次目标文件状态；两次之间发生替换则跳过该条。
- 回滚同样拒绝在备份目录内使用符号链接逃逸。

## 4 约束与边界

4.1 规则引擎源码与既有只读看板接口不变；冻结文件见第 13 节。
4.2 路径安全复用 `resolve_repo_root`：禁止 `..` 上级跳转、设备 / UNC 路径、控制字符、系统敏感目录；`file_path` 与 `backup_path` 另行做仓库/备份归属校验。
4.3 备份目录必须解析后位于被巡检仓库根之外；解析后落在仓库内则拒绝并返回 `FIXER_BACKUP_DIR_FORBIDDEN`。
4.4 仅处理 UTF-8 文本（含 UTF-8 BOM）；GBK 等其他编码、二进制、解码失败的文件跳过并标记不可修复。preview 默认 `fixable=false`；`strict=true` 时返回 `FIXER_FILE_UNDECODABLE`（422）。
4.5 不执行 / 编译 / 导入被扫描代码；默认离线，不联网。
4.6 写入前一致性校验：补丁对应的旧行必须与文件当前内容一致；比对粒度为整行文本（去除行尾换行符后逐字符比较）。不一致则该条跳过，防止陈旧补丁覆盖他人改动。
4.7 写入沿用原文件编码（UTF-8 / UTF-8 BOM）、换行风格与文件权限；不做整文件重排。写入方式为同目录临时文件 + `rename` 原子替换；临时文件失败时删除。权限不足或文件只读时记 skipped，不中断其他文件。
4.8 单次 apply 仅处理本次勾选条目，不批量遍历全仓自动改。
4.9 并发 apply 使用进程内单锁按仓库串行化；同一仓库同时只允许一个 apply/rollback 写操作。锁等待超时 5 秒，超时返回 **503 + `FIXER_IO_ERROR`**，不并发写同一文件。

## 5 可修复规则与修复动作

### 5.1 白名单（本轮唯一）
- `rule_id = link-005`：Markdown 链接目标包含未编码空格。
- 修复动作：把 inline / image / definition 链接目标中的半角空格编码为 `%20`，其余字符保持不动。
- 示例：
  - 原行：`[目标含空格](./lab 02.md)`
  - 新行：`[目标含空格](./lab%2002.md)`
- 定位方式：fixer 重新读取文件，按 Markdown 链接正则定位该行对应链接；不依赖引擎内部状态。
- 解析口径必须与 `link_check` 对齐：
  - 覆盖 inline、image、definition；reference 链接按既有规则跳过定义检查，不生成 link-005 补丁。
  - definition 的 title 不修改，只处理 target 中的空格。
  - 已用尖括号包裹的目标不会命中 link-005，无需处理。
  - 转义字符、锚点、已有 `%20` 保持不动，避免重复编码。
- 同一行存在多个未编码空格链接时，在该行生成**一个补丁**，一次性替换该行所有命中的链接目标；`old_line` / `new_line` 为整行。
- 实现优先只读复用 `link_check` 的公开链接解析函数；若必须自建正则，必须用测试锁定其覆盖范围（inline/image/definition、尖括号、title、转义），防止与引擎漂移。

### 5.2 不可自动修复（本轮仅给建议）
- 命名 / 目录改名与移动（牵动 import、调用处与文档引用）。
- 缺注释、缺文件头（需撰写内容）。
- 高危写法替换（属于语义改写，需结合上下文）。
- 敏感信息（正确动作是轮换密钥，不删除文件中的记录）。
- 大文件拆分或移出仓库。
- 空目标链接、缺定义引用（目标指向需用户补全）。
- 其余 link-001 / 002 / 003 / 004 / 006 / 007 / 008 及 naming、code、sensitive 全部规则。

### 5.3 白名单单一来源
- 后端白名单常量为唯一判定来源：只有 `link-005` 返回 `fixable=true`。
- `issues` 响应没有 `fixable` 字段；前端按 `rule_id === 'link-005'` 决定是否显示"查看修复"入口。
- 前端入口只影响展示；是否真正可修复以 preview 的 `fixable` 为准。
- 前后端白名单必须保持一致；变更白名单需同时修改两端并更新测试。

## 6 接口契约

### 6.1 POST `/api/fixer/preview`

请求：
```json
{
  "repo": "demo-repo",
  "issues": [
    {
      "file_path": "docs/lab02_broken_link.md",
      "line_no": 13,
      "rule_id": "link-005",
      "excerpt": "[目标含空格](./lab 02.md)"
    }
  ],
  "strict": false
}
```

响应：
```json
{
  "repo": "demo-repo",
  "patches": [
    {
      "patch_id": "p1",
      "file_path": "docs/lab02_broken_link.md",
      "line_no": 13,
      "rule_id": "link-005",
      "fixable": true,
      "old_line": "[目标含空格](./lab 02.md)",
      "new_line": "[目标含空格](./lab%2002.md)",
      "diff": "unified diff 文本",
      "reason": null
    }
  ]
}
```

- `repo` 只返回仓库标识 / 相对名，禁止返回本机绝对路径。
- `patch_id` **仅本次 preview 响应内有效**，仅用于前端展示与匹配；**不跨请求引用**，服务端不得凭 patch_id 直接改文件。
- 非白名单规则、定位失败、行号越界、尖括号包裹、符号链接、不可解码：`fixable=false`，`reason` 说明原因，不返回 old / new / diff。
- 请求 `strict=true` 时，存在不可解码文件返回 422 `FIXER_FILE_UNDECODABLE`；存在 `file_path` 越界返回 403 `REPO_FORBIDDEN` 或 400 `FIXER_INVALID_SELECTION`。
- preview 不落盘、不创建备份、不修改仓库。

### 6.2 POST `/api/fixer/apply`

请求：
```json
{
  "repo": "demo-repo",
  "backup_dir": "D:\\Backup\\RepoGuard",
  "on_stale": "skip",
  "strict": false,
  "selections": [
    {
      "file_path": "docs/lab02_broken_link.md",
      "line_no": 13,
      "rule_id": "link-005",
      "old_line": "[目标含空格](./lab 02.md)"
    }
  ]
}
```

- `selections` 每项必须带完整定位 `{file_path, line_no, rule_id, old_line}`；不得只传 patch_id。
- 服务端必须按 `file_path` + `line_no` + `rule_id` 重新读取并生成补丁，再与 `old_line` 比对；比对通过后才允许写入。
- `selections` 为空、缺字段、重复、非白名单、无法定位：400 `FIXER_INVALID_SELECTION`。
- `on_stale` 取值 `skip`（默认）/ `reject`；`reject` 时任一旧行不一致 → 409 `FIXER_STALE_PATCH`，整请求不写入。
- `strict=true` 时，存在不可解码文件 → 422 `FIXER_FILE_UNDECODABLE`，整请求不写入。
- 同一文件多条补丁按文件去重，只备份一次；同一行多个空格链接已合并为一个补丁。
- 处理顺序：校验仓库 / 备份目录 / 所有 file_path → 逐条重建并校验补丁 → 按文件分组去重 → 备份所有待改文件 → 逐文件原子写入 → 汇总。
- 备份目录必须已存在且可写，不自动创建；备份失败则该文件不写入，记 skipped 或 `FIXER_IO_ERROR`（请求级）。
- 多文件写入中途失败按文件粒度处理：已成功写入的文件不回滚，已备份原件保留；未成功文件记 skipped / failed，用户可后续 rollback 已成功项。
- 并发 apply 通过进程内单锁按仓库串行化。

响应：
```json
{
  "repo": "demo-repo",
  "backup_id": "20261117-230512-123",
  "applied": [
    {
      "patch_id": "p1",
      "file_path": "docs/lab02_broken_link.md",
      "line_no": 13,
      "after_sha256": "…"
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
      "file_path": "docs/lab02_broken_link.md",
      "backup_path": "20261117-230512-123/demo-repo/docs/lab02_broken_link.md",
      "captured_at": "2026-11-17T23:05:12Z"
    }
  ]
}
```

- 响应不回传 `backup_dir` 绝对路径；`backup_path` 为相对 `backup_dir` 的路径。
- `applied` / `skipped` / `backups` 中的文件路径均为仓库内相对路径。
- `after_sha256` 用于回滚前检测文件是否被手工修改。

### 6.3 POST `/api/fixer/rollback`

请求：
```json
{
  "repo": "demo-repo",
  "backup_dir": "D:\\Backup\\RepoGuard",
  "backup_id": "20261117-230512-123",
  "force": false,
  "strict": false,
  "backups": [
    {
      "file_path": "docs/lab02_broken_link.md",
      "backup_path": "20261117-230512-123/demo-repo/docs/lab02_broken_link.md",
      "after_sha256": "…"
    }
  ]
}
```

- `backup_path` 必须是相对路径；规范化后必须位于 `backup_dir/backup_id` 之内。越界、绝对路径、`..`、符号链接逃逸 → 403 `FIXER_BACKUP_PATH_FORBIDDEN`。
- `file_path` 必须是仓库内相对路径；越界拒绝。
- 回滚前检测目标文件是否在 apply 后被手工修改：当前文件 SHA-256 与 `after_sha256` 不一致时：
  - 默认 `force=false`：该条记 failed，reason "文件已被手工修改"，不覆盖；
  - `strict=true`：409 `FIXER_ROLLBACK_CONFLICT`，整请求不覆盖；
  - `force=true`：允许覆盖，但响应必须明确列出覆盖项。
- 备份原件缺失：记 failed，不动目标文件。
- 回滚使用备份原件覆盖，保留原文件编码/权限；写入使用临时文件 + `rename` 原子替换。

响应：
```json
{
  "repo": "demo-repo",
  "restored": [{ "file_path": "docs/lab02_broken_link.md" }],
  "failed": [{ "file_path": "docs/other.md", "reason": "备份原件缺失" }]
}
```

- 响应只含相对路径；不返回绝对路径。

### 6.4 通用约定
- 三个接口仅接受 `POST`，`Content-Type: application/json`；其他方法 405 `METHOD_NOT_ALLOWED`，非 JSON 415 `UNSUPPORTED_MEDIA_TYPE`。
- 请求体上限 2 MB；超过返回 413 `PAYLOAD_TOO_LARGE`。`issues` / `selections` / `backups` 数量上限 200 条，超过返回 422 `VALIDATION_ERROR`。
- 请求/响应沿用既有 `ApiError` / `error_payload` 结构（`error.code/message/detail` + `request_id`）。
- 三个接口在桌面模式下可用；非桌面模式统一返回 404。

## 7 错误处理

### 7.1 错误结构
沿用既有 `ApiError` 与错误响应结构（code / message / detail / request_id）。错误详情不得出现绝对路径、文件全文、备份目录真实路径、堆栈。

### 7.2 错误码

| code | HTTP | 触发条件 |
|---|---|---|
| `FIXER_INVALID_SELECTION` | 400 | `selections` 为空、缺字段、重复、非白名单、无法定位 |
| `FIXER_BACKUP_DIR_FORBIDDEN` | 403 | 备份目录在仓库内、系统敏感目录、不存在或不可写 |
| `FIXER_BACKUP_PATH_FORBIDDEN` | 403 | `backup_path` 越界、绝对路径、`..`、符号链接逃逸 |
| `FIXER_STALE_PATCH` | 409 | `on_stale=reject` / `strict=true` 时旧行不一致，整请求未写入 |
| `FIXER_FILE_UNDECODABLE` | 422 | `strict=true` 时存在不可解码文件，整请求未写入 |
| `FIXER_ROLLBACK_CONFLICT` | 409 | `strict=true` 时检测到 apply 后手工修改，整请求未覆盖 |
| `FIXER_IO_ERROR` | 503 | 锁等待超时（5 秒）；或备份、写入、回滚的请求级 I/O 失败（非单条 skipped） |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | 非 `application/json` 请求 |
| `PAYLOAD_TOO_LARGE` | 413 | 请求体超过 2 MB |
| `REPO_FORBIDDEN` / `REPO_NOT_FOUND` / `INVALID_REPO_PATH` | 403 / 404 / 400 | 复用既有仓库校验错误 |
| `VALIDATION_ERROR` | 422 | 复用请求体字段校验 |
| `METHOD_NOT_ALLOWED` | 405 | 复用；非 POST 方法 |
| `INTERNAL_ERROR` | 500 | 兜底（500 仅用于未预期异常，不再用于 fixer I/O/锁） |

### 7.3 单条失败与请求级错误
- 默认：单条陈旧补丁、不可解码、不可写、备份失败均记入 `skipped` / `failed`，HTTP 200。
- 仅当请求显式 `strict=true` 或 `on_stale=reject` 时，才使用 409 / 422 整请求错误，且整请求不写入任何文件。
- `FIXER_INVALID_SELECTION` 与 `FIXER_BACKUP_*` 属于请求级错误，整请求不写入。

## 8 数据模型、备份与审计

### 8.1 补丁（内部）
`patch_id`、`file_path`、`line_no`、`rule_id`、`fixable`、`old_line`、`new_line`、`diff`、`reason`。

### 8.2 备份记录
`file_path`、`backup_path`（相对 `backup_dir`）、`captured_at`、`after_sha256`。

### 8.3 备份目录布局
```
<backup_dir>/<backup_id>/<repo_label>/<原相对路径>
```
- `backup_id`：本地时间 `YYYYMMDD-HHMMSS-fff`；同秒冲突追加 `-<6位十六进制随机后缀>`；仍冲突追加 `-<序号>`。
- `repo_label`：仓库相对名 / dashboard 仓库标识，并为避免同名冲突追加 8 位短哈希（`name-8hex`）；不得使用绝对路径。
- `<原相对路径>`：保留仓库内相对路径与 `/` 分隔。
- 多仓库共用同一 `backup_dir` 时，按 `repo_label` 分层，避免同名文件冲突。
- 不写备份清单文件；清单随 apply 响应返回，由前端本次会话内存暂存。

### 8.4 会话清单与历史列表
- **本轮不做历史备份列表页**，不提供按时间戳浏览/查询备份的接口。
- 回滚清单仅保留在本次会话前端内存；刷新页面或关闭应用后不可回滚。
- 用户如需保留，需自行记录 `backup_dir` / `backup_id`。

### 8.5 审计日志
- apply / rollback 必须记录结构化审计日志：时间（ISO 8601 UTC）、`request_id`、仓库标识、动作（apply/rollback）、相对文件路径、规则、old/new 摘要（截断 ≤200 字符、脱敏）、相对备份路径、结果、耗时。
- 禁止记录绝对路径、文件全文、密钥、原始 webhook payload。
- 日志输出不得落在被巡检仓库内。

### 8.6 备份保留与清理
- 备份**不自动清理**；保留责任归用户。
- 本层不提供自动清理接口、不删除 `artifacts` 或备份目录。
- 文档需说明备份占用与手工清理方式。

## 9 测试要求（unittest，既有基线不得破坏）

### 9.1 文件与执行方式
- 新增 `backend/tests/test_fixer.py`。
- 统一 `python -m unittest`；API 级用例使用既有 `httpx` 的 ASGI 传输（`WebhookASGIClient`），不启动真实端口、不使用 `TestClient`、不引入 pytest。
- 文件系统用例使用 `tempfile.TemporaryDirectory()` 临时仓库；禁止写入真实 `demo-repo`。
- 备份目录使用仓库外临时目录；测试结束清理。
- 符号链接用例使用 `unittest.mock.patch` 模拟 `lstat`/解析结果，**不依赖真实创建符号链接**，避免增加 skip。

### 9.2 新增 16 条用例
1. `test_preview_link005_inline_image_definition`：三类链接均生成 `%20`，old/new/diff 正确，definition title 不变。
2. `test_preview_angle_wrapped_and_missing_target_not_fixable`：尖括号包裹、定位不到、行号越界 → `fixable=false`。
3. `test_preview_non_whitelisted_rule_not_fixable`：非 link-005 一律 `fixable=false`。
4. `test_preview_rejects_file_path_outside_repo`：`file_path` 含 `..` / 绝对路径 → 拒绝。
5. `test_preview_rejects_symlink_escape`：模拟符号链接指向仓库外 → 拒绝/不可修复。
6. `test_backup_dir_inside_repo_rejected`：备份目录在仓库内 → 403 `FIXER_BACKUP_DIR_FORBIDDEN`。
7. `test_apply_backs_up_before_write_and_bytes_match`：先备份后写入，备份字节与原件一致。
8. `test_apply_stale_old_line_skipped`：旧行变化 → 该条 skipped，不写入。
9. `test_apply_multi_patch_same_file_backs_up_once`：同文件多补丁只备份一次。
10. `test_apply_same_line_multiple_links_single_patch`：同一行多个空格链接合并为一个补丁。
11. `test_rollback_restores_original_bytes`：回滚后内容与原始字节一致。
12. `test_rollback_backup_path_escape_rejected`：`backup_path` 越界/绝对路径 → 403。
13. `test_rollback_detects_manual_modification`：apply 后手工修改 → 默认拒绝覆盖并记 failed。
14. `test_apply_undecodable_and_unwritable_skipped`：GBK/二进制/只读文件 → skipped，不中断其他文件。
15. `test_preview_accepts_repo_identity_name`：传仓库标识（目录名）可解析到白名单根目录，preview 返回 200 且补丁可修复。
16. `test_preview_rejects_unknown_repo_identity`：未知标识既非白名单目录名也非默认仓库，仍按原口径拒绝（400 `INVALID_REPO_PATH`）。

其中至少 6 条（1、3、4、6、8、11）通过 ASGI 调用三个 POST 端点，覆盖请求/响应契约与错误码。

### 9.3 基线与 skipped 口径
- 当前既有全量：`Ran 452 tests` → `OK (skipped=4)`（性能开关 1 + 既有符号链接平台波动 2 + 可选回环 1）。
- 新增 14 条后：`Ran 466 tests` → `OK (skipped=4)`，即 462 passed / 0 failed / 4 skipped。
- 新增用例不得增加 skip；符号链接用例用 mock 模拟。
- 既有 2 条 `test_repo_walk` 符号链接用例仍可能因平台在 failed / skipped 间漂移，按既有口径单列，不修改测试。
- 命令：`cd backend && <uv CPython 3.11.15> -m unittest discover -s tests -t .`；新增单跑：`python -m unittest tests.test_fixer`。

### 9.4 冻结与回归
- 13 个冻结文件 + `requirements.txt` + `static/index.html`：15 项 SHA-256 全部一致。
- `scripts/verify_frozen_hashes.py` 更新：`app.py` 增量校验基线切换为 `.codeartsdoer/evidence/stage6/app.py.stage6.orig`（当前 194 行 `app.py` 快照），期望 **相对 stage6 快照 +2/-0**（fixer 自身 1 行 import + 1 行 include_router）；阶段 5 的 `.codeartsdoer/evidence/stage5/app.py.orig` 与 15 项哈希证据保留不动；其余 15 项哈希、脚本结构、退出码语义不变。
- 既有偏差登记：`app.py` 相对 `evidence/stage5/app.py.orig` 的存量差异为 **+8/-1**（storage 初始化、static 挂载调整、dashboard 挂载），属阶段 5 后既有变更，**不计入 fixer 增量**。
- 既有 29 个测试文件零改动。
- 既有 dashboard GET 路由行为不变；`/api/fixer/*` 仅在 desktop_mode 可用（非桌面 404）。

### 9.5 前端与桌面验收
- 前端构建：`cd frontend && npm ci && npm run build` 成功，`dist/index.html` 存在。
- 前端静态红线：全站 0 `v-html`；请求只经 `api/fixer.js`；组件/视图无 `fetch(` 与 `/api/` 字面路径。
- 桌面 GUI 手工验收项见 12.8。

## 10 部署与环境限制

### 10.1 路由暴露边界
- fixer router 在 `app.py` 中仅以 2 行挂载（1 import + 1 include_router）；每个端点通过依赖校验 `WebSettings.desktop_mode`，**仅桌面模式可用**；生产 Web（非桌面模式）所有端点返回 404。
- 不经过 nginx / 公网反代；不得把 fixer 挂到既有 GET router 或 dashboard router。
- 纯浏览器 / Vite dev 模式无 preload：前端隐藏修复入口并提示"修复功能仅在桌面版可用"。
- 本轮不改 deploy 产物；如部署侧需要额外保险，可在 nginx 增加 `/api/fixer` 404，但不作为本轮范围。

### 10.2 前端文件与依赖
- 新增 `frontend/src/api/fixer.js`：POST 封装，复用 `client.js` 已支持的 `requestJson(path, { method:'POST', body })`；不新增依赖。
- 新增 `frontend/src/components/FixPreviewDialog.vue`：diff 用 `<pre>` 文本渲染；旧/新行颜色仅作强调，同时提供文字标识。**查看修复触发按钮可并入本组件**。
- 修改 `frontend/src/views/IssuesView.vue`：仅做 import 与模板挂载（在 `#detail` 插槽内挂载 `FixPreviewDialog`），**不承载按钮/弹窗逻辑**，不改变既有筛选/分页逻辑。
- 前端 `package.json` / `package-lock.json` **零改动**；`desktop/package.json` / `package-lock.json` **零改动**。
- 不引入 diff 渲染库、UI 库、测试框架。

### 10.3 桌面壳
- 复用 `desktop/main/main.js` 的 `repoguard:pick-directory` 与 `desktop/main/preload.js` 暴露的 `window.repoguard.pickDirectory()`；**不新增目录选择 IPC**。
- 桌面壳仅做必要的最小改动（如前端直接复用则无需改）；不得改动 Electron 依赖版本与打包配置。
- 备份目录为仓库内或系统敏感目录时，由服务端拒绝并把中文原因返回前端。

### 10.4 文档
- 本轮登记 `docs/fixer_usage.md` 为后续 design/tasks 交付项，内容至少覆盖：功能边界与桌面模式前提、备份目录选择、diff 确认、apply / rollback、错误码、审计日志、限制（无历史备份列表、无自动清理、无 git 提交）、非桌面模式降级。
- 文档示例路径使用相对路径与占位符，不写真实密钥与个人绝对路径。

## 11 风险与缓解

- 风险：自动改源码造成误改 → 缓解：仅白名单机械规则；diff 预览；逐条勾选；写前一致性校验；原件备份；可回滚。
- 风险：备份误入被巡检仓库 → 缓解：服务端强制校验备份目录在仓库根之外。
- 风险：陈旧补丁覆盖并发改动 → 缓解：old_line 比对，不一致即跳过；严格模式整请求拒绝。
- 风险：rollback 路径穿越读取任意文件 → 缓解：`backup_path` 必须位于本次 `backup_dir/backup_id` 内，拒绝 `..` 与符号链接。
- 风险：仓库内符号链接把写入引到仓库外 → 缓解：`file_path` 归属校验 + `lstat` 拒绝符号链接 + 写入前二次校验。
- 风险：写接口被公网调用 → 缓解：仅 desktop_mode 注册，不经 nginx；非桌面模式直接不可用。
- 风险：与既有只读规格口径冲突 → 缓解：本规格作为只读规格的补充例外单独归档；只读引擎与只读看板的代码、结论不变；app.py 增量与哈希脚本口径在冻结清单登记。

## 12 验收标准

1. 规则引擎冻结文件零改动；既有 GET 看板接口行为不变；`core/rules`、`requirements.txt`、frontend/desktop 依赖清单零改动。
2. preview 对 link-005（inline/image/definition）给出正确 old / new / diff；其余规则 `fixable=false`；响应不含绝对路径。
3. apply 每项 `selections` 带完整定位，服务端重建并比对 `old_line`；先备份后写入；备份目录在仓库外；陈旧补丁默认跳过，`on_stale=reject` 时 409 且不写入。
4. rollback 能还原被改文件；`backup_path` 越界 403；检测到 apply 后手工修改时默认拒绝覆盖，`strict=true` 时 409。
5. 前端仅对 link-005 显示修复入口；非桌面模式隐藏入口并提示；diff 弹窗无 `v-html`，旧/新行有文字标识；确认后触发复扫，被节流时给提示。
6. 后端新增 14 条测试全通过；全量 `Ran 466 tests` + `OK (skipped=4)` + 退出码 0；既有 2 条符号链接平台波动单列；前端 `npm ci` + `npm run build` 无编译错误。
7. 不做一键全改、不做 git 自动提交；不做历史备份列表页；备份不自动清理。
8. 桌面 GUI 验收：
   - 点击"选择备份目录"能调起既有系统目录选择框并返回绝对路径；
   - 取消选择不触发 apply；
   - 选择仓库内目录被拒绝并显示中文原因；
   - 非桌面浏览器模式不显示修复入口；
   - diff 弹窗可用键盘完成勾选与确认；
   - apply 成功后有备份清单与复扫提示；rollback 成功/冲突均有明确反馈。

## 13 冻结清单与不纳入范围

### 13.1 本轮零改动
- `core/rules/` 全部规则与引擎；`api/routes.py` 只读巡检契约。
- 既有 dashboard GET 路由与 `app/dashboard/**`（fixer 不改其代码）。
- `requirements.txt`；`frontend/package.json`、`frontend/package-lock.json`；`desktop/package.json`、`desktop/package-lock.json`。
- 既有 29 个测试文件；既有 4 份使用文档（rules_engine / web_api / repo_health_readme / webhook_openapi）。
- 既有 15 项哈希（13 个冻结文件 + requirements + static/index.html）：全部保持一致。
- deploy 22 个产物（本轮不改 nginx 与部署配置）。

### 13.2 本轮允许改动
- `backend/app/api/app.py`：仅新增 1 行 import + 1 行 `include_router`（共 2 行）；`desktop_mode` 判定在 fixer 端点依赖内完成，不增加 app.py 行数；不得改中间件/CORS/lifespan/静态挂载/既有路由。
- `scripts/verify_frozen_hashes.py`：`app.py` 增量校验基线切换为 `.codeartsdoer/evidence/stage6/app.py.stage6.orig`，期望相对该快照 **+2/-0**；其余 15 项哈希与脚本结构不变。
- 新增 `.codeartsdoer/evidence/stage6/app.py.stage6.orig`（tasks/编码阶段从当前 194 行 `app.py` 生成，作为 fixer 阶段基线）；阶段 5 的 `evidence/stage5/app.py.orig` 与 15 项哈希证据保留不动。
- 新增 `backend/app/fixer/**`、`backend/tests/test_fixer.py`。
- 新增 `frontend/src/api/fixer.js`、`frontend/src/components/FixPreviewDialog.vue`；最小修改 `frontend/src/views/IssuesView.vue`。
- 新增 `docs/fixer_usage.md`（按 10.4）。
- `desktop/main/main.js` / `desktop/main/preload.js`：仅在确有必要时做最小改动；优先复用既有 `pickDirectory`，不新增 IPC。

### 13.3 不纳入本轮
- 命名 / 移动类自动修复；注释补全；高危写法自动替换；敏感信息自动删除；大文件拆分；空目标 / 缺定义链接自动补全。
- 一键全改；自动提交 git；服务端定时自动修复。
- 历史备份列表页 / 备份查询接口；备份自动清理。
- 非桌面模式（纯浏览器）下的备份目录选择与写入能力。
- fixer 的 nginx / 公网暴露与鉴权体系。
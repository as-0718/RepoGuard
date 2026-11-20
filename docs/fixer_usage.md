# RepoGuard 修复辅助层（fixer）使用文档

> 本文面向首次使用 fixer 的维护者，说明功能边界、桌面前提、备份、预览确认、写入与回滚、错误码与限制。

## 1. 功能边界与只读例外

fixer 是既有只读巡检能力的**补充例外**：规则引擎、巡检结论与看板只读接口保持不变，修复动作只发生在独立 fixer 层。

- 仅处理白名单规则 `link-005`、`code-012`、`code-010`：
  - `link-005`：Markdown 链接目标中的半角空格编码为 `%20`，不改成尖括号包裹；
  - `code-012`：`== None` / `!= None` 等价改写为 `is None` / `is not None`；
  - `code-010`：`breakpoint()` / `pdb.set_trace()` 所在整行注释化，保留缩进与原文并加行尾标注，不删行以便回滚。
- 非白名单规则一律只读建议，不生成补丁、不写入文件。
- 没有一键全改；每条补丁必须预览、勾选、确认后才写入。
- 不做 git 自动提交。

## 2. 桌面模式前提与非桌面降级

fixer 只在 Electron 桌面壳内可用，由本地前端调用，不经过 nginx 或公网反代。

- 桌面壳暴露 `window.repoguard.pickDirectory()` 时才显示“查看修复”入口。
- 纯浏览器 / Vite dev 模式没有 preload，修复入口不显示，并提示“修复功能仅在桌面版可用”。
- 非桌面模式下后端 fixer 端点统一返回 404。

## 3. 备份目录选择与仓库外要求

每次 apply 前由用户选择备份目录：

1. 在弹窗内点击“选择备份目录”。
2. 在系统目录选择框中选择一个目录。
3. 取消选择会停留，不触发写入。

备份目录必须：

- 位于被巡检仓库之外；
- 已存在且可写；
- 不是系统敏感目录；
- 不是符号链接逃逸路径。

服务端会再次校验；不合规返回 `FIXER_BACKUP_DIR_FORBIDDEN`。

## 4. diff 确认与逐条勾选

点击“查看修复”后，前端调用 preview，后端只读生成补丁，不落盘。

- 弹窗展示旧行（红色“旧”）与新行（绿色“新”）。
- unified diff 按行展示：`+` 为“新增”、`-` 为“删除”、`@@` 为位置信息。
- 补丁列表默认勾选所有可修复项；可逐条取消。
- 不可修复项显示原因，不提供勾选。
- 预览不写文件、不创建备份。

## 5. apply 与 rollback

### apply

1. 勾选补丁并选择备份目录。
2. 点击“确认写入”。
3. 服务端按 `file_path + line_no + rule_id + old_line` 重建补丁并比对旧行。
4. 先备份原件，再逐文件原子写入。
5. 返回 `applied`、`skipped`、`backups`。

- 旧行不一致的条目进入 `skipped`，不写入。
- 同一文件多条补丁只备份一次。
- 写入后前端触发复扫；若 60 秒缓存或 10 秒刷新节流生效，会提示稍后更新。

### rollback

1. 使用本次 apply 返回的 `backup_id` 与 `backups`。
2. 点击“回滚本次写入”。
3. 服务端校验备份路径归属，并检测目标文件是否在 apply 后被手工修改。
4. 默认拒绝覆盖手工修改的文件；失败项返回 `failed`。

回滚清单只保留在本次会话前端内存；刷新页面后不可回滚。

## 6. 错误码

| 错误码 | HTTP | 含义 |
|---|---|---|
| `FIXER_INVALID_SELECTION` | 400 | 补丁定位不合法、重复或无法定位 |
| `FIXER_BACKUP_DIR_FORBIDDEN` | 403 | 备份目录在仓库内、系统敏感、不存在或不可写 |
| `FIXER_BACKUP_PATH_FORBIDDEN` | 403 | 备份路径越界、绝对路径或符号链接逃逸 |
| `FIXER_STALE_PATCH` | 409 | 旧行已变化，拒绝写入 |
| `FIXER_FILE_UNDECODABLE` | 422 | 文件不是可处理的 UTF-8 文本 |
| `FIXER_ROLLBACK_CONFLICT` | 409 | 目标文件在 apply 后被手工修改，拒绝覆盖 |
| `FIXER_IO_ERROR` | 503 | 仓库写操作排队超时或请求级 I/O 失败 |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | 请求不是 `application/json` |
| `PAYLOAD_TOO_LARGE` | 413 | 请求体超过 2 MB |

`REPO_*`、`VALIDATION_ERROR`、`NOT_FOUND`、`INTERNAL_ERROR` 沿用看板既有错误口径。

## 7. 审计日志

apply / rollback 会输出结构化审计日志到 stdout，与既有服务日志同一出口，不写独立日志文件、不做轮转。

记录字段包括：

- 时间（UTC）`time`；
- `request_id`；
- 仓库标识 `repo_label`；
- 动作（apply / rollback）`action`；
- `files`：被改文件的相对路径 `file_path`、规则 `rule_id`、旧行 / 新行摘要（`old_line` / `new_line`，截断 200 字符）；
- 结果 `result` 与耗时 `duration_ms`。

被改文件的修改时间（mtime）随修复事件写入本地 SQLite；备份路径在 apply 响应的 `backups` 中返回，由前端本次会话暂存，二者都不进入 stdout 审计日志。日志不记录绝对路径、文件全文或密钥。

## 8. 限制

- 白名单仅 `link-005`、`code-012`、`code-010`；命名、移动、注释、其余高危写法、敏感信息、大文件等规则不自动修复。
- 不做一键全改。
- 不做 git 提交，也不做自动提交。
- **不做历史备份列表页**；回滚清单仅本次会话前端暂存。
- **备份不自动清理**，保留责任归用户。
- 单实例进程内锁：同一仓库的 apply / rollback 串行，等待超时 5 秒。
- 非桌面模式不提供任何写能力。

## 9. 备份布局与手工清理

备份目录布局：

```text
<backup-root>/
  <backup-id>/
    <repo-label>/
      <仓库内相对路径>
```

- `backup-id` 形如 `YYYYMMDD-HHMMSS-fff`；同毫秒冲突追加短随机后缀。
- 备份文件保留原相对路径与字节。
- 不写备份清单文件；清单随 apply 响应返回，由前端本次会话内存暂存。

清理方式：由用户自行进入 `<backup-root>`，按 `<backup-id>` 目录手工删除不再需要的备份。fixer 不提供自动清理接口，也不会删除备份目录本身。
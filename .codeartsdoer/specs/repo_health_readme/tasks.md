# RepoGuard 阶段 3 编码任务规划（tasks.md）

> feature：`repo_health_readme`
> 唯一依据：`.codeartsdoer/specs/repo_health_readme/spec.md`（1148 行）、`.codeartsdoer/specs/repo_health_readme/design.md`（1806 行，含 2.2.1 逐文件签名、2.6 僵尸算法、2.7 报告契约、2.8 README 算法、2.9 CLI、2.10 导入兼容、2.12 测试计划）。
> 本文只做任务拆解与验收规划，**不包含任何实现代码**；所有路径均为仓库相对路径；产品代码根为 `backend/app/`。
> 执行原则：只新增文件；不修改冻结文件、`backend/app/api/**`、`backend/app/static/index.html`、`backend/requirements.txt`、`backend/tests/test_engine.py`、`backend/tests/test_cli.py`、`spec.md`、`design.md`。

---

## 1. 任务拓扑与依赖图

### 1.1 主任务总览

| 编号 | 主任务 | 主要交付物（仓库相对路径） | 前置任务 | 并行组 | 关键路径 |
|------|--------|--------------------------|----------|--------|----------|
| 1 | 改动前基线采样与冻结证据 | 仓库外基线记录 | — | — | 是 |
| 2 | 编码容错读取包装 | `backend/app/shared/text_io.py` | 1 | P1 | 是 |
| 3 | 仓库遍历、路径安全与清单生成 | `backend/app/shared/repo_walk.py` | 1 | P1 | 是 |
| 4 | shared 包公共导出 | `backend/app/shared/__init__.py` | 2、3 | — | 是 |
| 5 | README 数据契约 | `backend/app/readme/models.py` | 1 | P1 | 是 |
| 6 | 文档标题提取与 Demo 识别 | `backend/app/readme/scanner.py` | 2、3、4、5 | — | 是 |
| 7 | 健康报告数据契约、映射与排序 | `backend/app/health/models.py` | 5、6 | P2 | 是 |
| 8 | 僵尸候选三条件判定 | `backend/app/health/zombie.py` | 3、4、7 | P2 | 是 |
| 9 | 全仓巡检编排与报告映射 | `backend/app/health/service.py` | 6、7、8 | — | 是 |
| 10 | 健康报告 text/JSON 渲染 | `backend/app/health/render.py` | 7 | P3 | 是 |
| 11 | 健康巡检 CLI | `backend/app/health/cli.py` | 3、4、7、9、10 | P4 | 是 |
| 12 | health 包公共导出 | `backend/app/health/__init__.py` | 7、9 | P3 | 否 |
| 13 | 目录索引构建与片段渲染 | `backend/app/readme/index.py` | 5、6 | P2 | 否 |
| 14 | README 定位、区块识别与差异 | `backend/app/readme/compare.py` | 5、6 | P2 | 否 |
| 15 | README 报告 text/JSON 渲染 | `backend/app/readme/render.py` | 5 | P3 | 否 |
| 16 | README 扫描编排与报告组装 | `backend/app/readme/service.py` | 6、13、14、15 | P4 | 否 |
| 17 | README CLI | `backend/app/readme/cli.py` | 3、4、14、15、16 | P5 | 是 |
| 18 | readme 包公共导出 | `backend/app/readme/__init__.py` | 5、16 | P6 | 否 |
| 19 | 遍历与路径安全测试 | `backend/tests/test_repo_walk.py` | 4 | T1 | 否 |
| 20 | 巡检复用、映射与只读测试 | `backend/tests/test_health_service.py` | 9、11 | T2 | 是 |
| 21 | 僵尸判定测试 | `backend/tests/test_health_zombie.py` | 8 | T2 | 否 |
| 22 | 健康报告渲染测试 | `backend/tests/test_health_report.py` | 10 | T3 | 否 |
| 23 | 健康巡检 CLI 测试 | `backend/tests/test_health_cli.py` | 11 | T3 | 否 |
| 24 | README 扫描测试 | `backend/tests/test_readme_scan.py` | 6 | T2 | 否 |
| 25 | README 索引测试 | `backend/tests/test_readme_index.py` | 13 | T3 | 否 |
| 26 | README 对比测试 | `backend/tests/test_readme_compare.py` | 14 | T3 | 否 |
| 27 | README CLI 测试 | `backend/tests/test_readme_cli.py` | 17 | T4 | 是 |
| 28 | 导入兼容逐文件核查 | 核查记录（仓库外或终端留存） | 4、11、12、17、18 | — | 是 |
| 29 | 回归与冻结哈希门禁 | 回归记录 | 27、28 | — | 是 |
| 30 | 只读实测与零网络/零端口静态检查 | 实测记录 | 29 | — | 是 |
| 31 | 中文使用文档 | `docs/repo_health_readme_usage.md` | 17、29 | D | 否 |
| 32 | 交付清单与最终验收 | 最终交付清单 | 30、31 | — | 是 |

### 1.2 依赖图

```text
[1 基线]
  ├─> [2 shared.text_io] ──────────────┐
  ├─> [3 shared.repo_walk] ──┐         │
  └─> [5 readme.models] ──┐  │         │
                          v  v         v
                     [4 shared.__init__]
                          │
[5] ──> [6 readme.scanner] <── [2][3][4]
            │
            ├─> [7 health.models] ─> [8 health.zombie] ─> [9 health.service]
            │        │                                   │
            │        ├─> [10 health.render] ─────────────┴─> [11 health.cli]
            │        └─> [12 health.__init__]
            ├─> [13 readme.index] ─┐
            ├─> [14 readme.compare]┼─> [16 readme.service] ─> [17 readme.cli]
[5] ──> [15 readme.render] ────────┘                              │
                                                                  ├─> [18 readme.__init__]
                                                                  └─> [27 test_readme_cli]

测试：19←4；20←9,11；21←8；22←10；23←11；24←6；25←13；26←14；27←17
门禁：28←4,11,12,17,18 → 29←27,28 → 30←29 → 32←30,31；31←17,29
```

### 1.3 并行组与关键路径

- **P1（基线后）**：主任务 2、3、5 可并行。
- **P2（scanner 后）**：主任务 7、13、14、15 可并行；主任务 8 依赖 7。
- **P3（health.models 后）**：主任务 10、12 可并行。
- **P4（service 后）**：主任务 11、16 可并行。
- **P5（readme.service 后）**：主任务 17、18 可并行。
- **测试组**：T1=19；T2=20、21、24；T3=22、23、25、26；T4=27。测试可在对应模块完成后立即开始，不等待全部产品代码。
- **关键路径**：`1 → 2/3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 20 → 29 → 30 → 32`；README 侧关键路径为 `6 → 13/14/15 → 16 → 17 → 27 → 29 → 30 → 32`。
- **串行硬约束**：`shared → readme.models/scanner（health 需要 Demo 统计）→ health.models/zombie/service → health.render/cli`；README 的 `index/compare/service/render/cli` 在 scanner 后可并行；测试与文档最后；回归与哈希验收最后。

### 1.4 需求覆盖映射

| spec 章节 | 覆盖主任务 |
|-----------|-----------|
| 4.1 仓库根定位与校验 | 3、19 |
| 4.2 递归遍历规则 | 3、19 |
| 4.3 四模块复用契约 | 8、9、20 |
| 4.4 读取、编码、超大文件 | 2、9、20 |
| 5.1 Markdown 链接批量校验 | 9、10 |
| 5.2 代码文件规范问题 | 9、10 |
| 5.3 敏感信息与大文件 | 9、10、20 |
| 5.4 僵尸/废弃判定 | 8、21 |
| 5.5 风险等级映射 | 7、10、22 |
| 6 健康报告数据契约 | 7、10、22 |
| 7.1 文档扫描与标题提取 | 6、24 |
| 7.2 Demo 工程识别 | 6、24 |
| 7.3 目录索引结构 | 13、25 |
| 7.4 现有 README 对比 | 14、26 |
| 7.5 README 只读契约 | 14、26、27 |
| 8 CLI 与入口 | 11、17、23、27 |
| 9 文件路径清单与职责 | 2～18、28 |
| 10 非功能约束 | 29、30 |
| 11 测试与验收 | 19～30 |

### 1.5 全局执行纪律与门禁

- [ ] 只新增 `backend/app/shared/**`、`backend/app/health/**`、`backend/app/readme/**`、9 个测试文件、1 个文档；不修改任何既有文件。
- [ ] 13 个冻结文件零改动：`engine.py`、`naming.py`、`code_scan.py`、`link_check.py`、`sensitive.py`、`common/__init__.py`、`common/config.py`、`common/file_io.py`、`common/manifest.py`、`common/models.py`、`common/report.py`、`rules/__init__.py`、`tests/test_cli.py`。
- [ ] 不修改 `backend/tests/test_engine.py`（含 `test_import_direction`）、不修改 `backend/app/api/**`、`backend/app/static/index.html`、`backend/requirements.txt`。
- [ ] 所有新增测试使用 `unittest`，**不使用 pytest**，不新增依赖；每个测试文件可被 `unittest discover` 发现。
- [ ] 所有新增代码只使用 Python 3.10+ 标准库；不联网、不监听端口、不启动 uvicorn/FastAPI、不导入 Web 框架。
- [ ] 每个主任务完成后必须回报：`主任务 N 完成：实际写入 <仓库相对路径>；验收项 X/Y 通过；未修改文件：<清单>；下一任务：N+1`。
- [ ] 任一验收项失败立即停止，不进入后续任务；修复后从该任务重新验收，不得跳过门禁。
- [ ] 自扫描判定口径：以**工具自身** `backend/app` 的真实路径是否位于扫描根内为准，不是「存在同名 `backend/app/` 目录」；`demo-repo/backend/app` 属于被巡检内容，`demo-repo` 可正常巡检。

---

## 2. 基线与 shared 公共包

## 主任务 1：改动前基线采样与冻结证据

- **交付物**：仓库外基线记录（终端留存或仓库外临时文件，禁止写入 `demo-repo/`）。
- **前置**：无。
- **输入**：现有 `backend/`、`demo-repo/`、13 个冻结文件。
- **输出**：5 类基线数值与哈希清单。
- **子任务与验收**：
  - [ ] 1.1 在 `backend/` 执行 `python -m unittest discover -s tests -v`，记录 `Ran 165 tests`、`OK (skipped=1)`，并确认 `test_performance_500` 为 skipped。
  - [ ] 1.2 在 `backend/` 执行 `python -m unittest tests.test_cli -v`，记录 12 passed。
  - [ ] 1.3 对 13 个冻结文件逐个计算 SHA-256，按固定顺序输出并保存到仓库外，作为后续差异基线。
  - [ ] 1.4 记录 `backend/requirements.txt` 的 SHA-256；记录 `backend/app/api/**`、`backend/app/static/index.html` 的文件清单。
  - [ ] 1.5 记录 `demo-repo/` 的完整文件清单与每个文件的 `size + sha256 + mtime` 快照。
  - [ ] 1.6 执行 `python -m unittest tests.test_engine.EngineTest.test_import_direction -v`（方法名以实际类名为准），确认通过，且未修改测试方法体。
- **停止条件**：任一项与 spec 11.2 / design 1.2.4 的基线不符时停止，先排查环境再继续。
- **路径回报**：回报基线记录所在路径（仓库外）与上述数值。

## 主任务 2：编码容错读取包装 `backend/app/shared/text_io.py`

- **交付物**：`backend/app/shared/text_io.py`。
- **前置**：主任务 1。
- **并行组**：P1（可与主任务 3、5 并行）。
- **输入**：`design.md` 2.2.1（3）、2.4.4；`spec.md` 4.4、7.1.4、10.9；阶段 1 `common/file_io.py`。
- **输出**：统一读取包装，不复制 BOM/UTF-8/GB18030 回退逻辑。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - 常量：`MAX_SCAN_BYTES: int = 5 * 1024 * 1024`、`MAX_TITLE_BYTES: int = 256 * 1024`、`MAX_REFERENCE_BYTES: int = 5 * 1024 * 1024`。
  - 复用类型：`TextReadResult`（来自 `..core.rules.common.file_io`）。
  - `read_text_for_scan(path: str | Path) -> TextReadResult`
  - `read_text_limited(path: str | Path, max_bytes: int) -> TextReadResult`
  - `read_title_source(path: str | Path, max_bytes: int = MAX_TITLE_BYTES) -> TextReadResult`
  - `is_binary_path(path: str | Path, binary_extensions: Sequence[str]) -> bool`
  - `normalize_newlines(text: str) -> str`
- **验收标准**：
  - [ ] 三个读取函数全部委托 `read_text_from_disk()`，新文件内不出现 BOM 去除、`utf-8`/`gb18030` 回退的重复实现。
  - [ ] 默认上限严格为 5 MB、标题 256 KB、引用 5 MB；不新增阶段 1 之外的阈值。
  - [ ] `is_binary_path()` 复用阶段 1 的扩展名黑名单与 NUL 采样语义，不复制规则表。
  - [ ] `normalize_newlines()` 只处理 `\r\n` 与 `\r`，不影响其他字符与行号语义。
  - [ ] 读取失败、无权限、编码失败时返回带错误种类的 `TextReadResult`，不抛未捕获异常、不写盘。
  - [ ] 导入形式：`from __future__ import annotations`、`from pathlib import Path`、`from typing import Sequence`、`from ..core.rules.common.file_io import ...`；无第三方、无网络库。
- **路径回报**：实际写入 `backend/app/shared/text_io.py`。

## 主任务 3：仓库遍历、路径安全与清单生成 `backend/app/shared/repo_walk.py`

- **交付物**：`backend/app/shared/repo_walk.py`。
- **前置**：主任务 1。
- **并行组**：P1（可与主任务 2、5 并行）。
- **输入**：`design.md` 2.2.1（2）、2.4.1～2.4.3；`spec.md` 4.1、4.2、4.3.3、10.8；阶段 1 `common/file_io.py`。
- **输出**：`WalkResult`（文件清单、跳过清单、超限标记、目录计数）与内存清单文本。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - 常量：`DEFAULT_MAX_FILES: int = 5000`、`MAX_WALK_DEPTH: int = 64`、`SKIP_DIR_NAMES: frozenset[str]`、`SKIP_DIR_SUFFIXES: tuple[str, ...] = (".egg-info",)`。
  - 异常：`RootValidationError(Exception)`，构造签名为 `__init__(self, reason: str, *, scan_root: str = "<repo>") -> None`。
  - `WalkOptions(max_files=5000, max_depth=64, skip_dir_names=SKIP_DIR_NAMES, follow_dir_symlinks=False, max_skipped_detail=200)`。
  - `WalkedFile(path, absolute_path, size, mtime, suffix)`，属性 `is_markdown -> bool`、`is_code -> bool`。
  - `WalkSkipped(path, reason, category)`。
  - `WalkResult(root, scan_root, files=(), skipped=(), exceeded_max_files=False, max_files=DEFAULT_MAX_FILES, directory_count=0)`，属性 `file_count`、`markdown_count`、`code_file_count`、`skipped_count`。
  - `resolve_default_repo(base: str | Path | None = None) -> Path`
  - `validate_repo_root(repo_root: str | Path, options: WalkOptions | None = None) -> Path`
  - `walk_repository(repo_root: str | Path, options: WalkOptions | None = None) -> WalkResult`
  - `to_manifest(files: Sequence[WalkedFile]) -> str`
  - `relative_posix(root: str | Path, path: str | Path) -> str`
  - `is_within_root(root: str | Path, candidate: str | Path) -> bool`
  - `scan_root_name(root: str | Path) -> str`
  - `is_tool_source_root(root: str | Path) -> bool`
- **验收标准**：
  - [ ] 默认根依次尝试 `../demo-repo`、`demo-repo`，取第一个存在且为目录者；都不存在抛中文 `RootValidationError`。
  - [ ] 显式根校验存在、目录、可读；返回 `resolve()` 后的真实路径；非法原因全部为中文。
  - [ ] 跳过目录名不区分大小写，完整覆盖 spec 4.2.2 的 18 项与 `.egg-info` 后缀；隐藏文件（如 `.env`、`.gitignore`）必须纳入，隐藏目录（如 `.github`）默认展开。
  - [ ] 深度上限默认 64，超限停止展开并记 `WalkSkipped(category="深度超限")`。
  - [ ] 文件数超过 `max_files` 时立即中止，返回 `exceeded_max_files=True` 且 `files=()`，绝不产出部分清单。
  - [ ] 目录符号链接不跟随；文件符号链接解析后越界记「符号链接逃逸，已跳过」且不读取；根内链接以链接相对路径入清单；断链记「符号链接目标不存在，已跳过」。
  - [ ] 文件名含 `\n`/`\r`、首尾空白、无法构造路径时跳过并记「文件名包含非法字符，无法生成清单行」，不伪造清单行。
  - [ ] `to_manifest()` 每文件一行 `M <相对路径>`，末行带换行，空清单返回空串；空格原样保留，行首 `M` 避免 `#` 被误判注释。
  - [ ] 输出路径统一 `/` 分隔、无盘符、无 `..`、不以 `/` 开头；文件按 `path` 升序，跳过项按 `(category, path)` 升序。
  - [ ] 自扫描拒绝以工具自身 `backend/app` 真实路径是否位于扫描根内为准；`demo-repo` 不得被误拒。
  - [ ] 遍历阶段只 `scandir`/`stat`，不读取文件内容、不创建/修改/删除/重命名、不 `utime`/`chmod`。
  - [ ] 导入形式：`from __future__`、`from dataclasses`、`from pathlib`、`from typing`、`from ..core.rules.common.file_io`；`import os` 用模块形式。
- **路径回报**：实际写入 `backend/app/shared/repo_walk.py`。

## 主任务 4：shared 包公共导出 `backend/app/shared/__init__.py`

- **交付物**：`backend/app/shared/__init__.py`。
- **前置**：主任务 2、3。
- **输入**：`design.md` 2.2.1（1）。
- **输出**：仅再导出，不含逻辑。
- **需要实现的公开符号**：
  - `WalkOptions`、`WalkedFile`、`WalkSkipped`、`WalkResult`、`RootValidationError`
  - `walk_repository`、`validate_repo_root`、`resolve_default_repo`、`to_manifest`、`relative_posix`、`is_within_root`、`scan_root_name`、`is_tool_source_root`
  - `TextReadResult`、`read_text_for_scan`、`read_text_limited`、`read_title_source`
  - `__all__` 覆盖上述符号。
- **验收标准**：
  - [ ] 文件只包含包标记、相对导入与 `__all__`，不含业务逻辑、无副作用。
  - [ ] `from app.shared import walk_repository, read_text_for_scan, WalkOptions` 可成功。
  - [ ] `shared/**` 不反向导入 `health`、`readme`、`app.api`；AST 检查命中 0。
- **路径回报**：实际写入 `backend/app/shared/__init__.py`。

---

## 3. README 基础层与 health 主链路

## 主任务 5：README 数据契约 `backend/app/readme/models.py`

- **交付物**：`backend/app/readme/models.py`。
- **前置**：主任务 1。
- **并行组**：P1。
- **输入**：`design.md` 2.2.1（11）、2.3.2、2.8.5；`spec.md` 7.1、7.3、7.4、6.1（同形字段）。
- **输出**：README 扫描与报告所需的全部冻结数据结构。
- **需要实现的类型与签名（与 design 2.2.1 一致）**：
  - 枚举：`TitleSource(Enum)`（`ATX="atx"`、`FALLBACK_FILENAME="fallback_filename"`）；`ReadmeStatus(Enum)`（`OK="正常"`、`PARTIAL_DEGRADED="部分降级"`、`INPUT_ERROR="输入错误"`）；`Confidence(Enum)`（`CONFIRMED="confirmed"`、`SUSPECTED="suspected"`）。
  - `TitleResult(title, source, line_no, truncated=False)`。
  - `DocEntry(path, title, title_source, line_no=None)`。
  - `DemoProject(path, confidence, evidence=())`。
  - `DemoUndetermined(path, reason)`。
  - `DemoScanResult(confirmed=(), suspected=(), undetermined=())`。
  - `TocItem(kind, path, title, depth, link, anchor, confidence)`。
  - `TocSection(name, items=())`。
  - `TocIndex(document_section, demo_section, root_readme_path=None)`，属性 `item_count -> int`、`all_items() -> tuple[TocItem, ...]`。
  - `TocEntryRef(path, title, depth, position, is_demo=False)`。
  - `TocBlock(start_line, end_line, marker_kind, heading_level, lines=())`。
  - `ReadmeDiff(change_type, path, old_title, new_title, old_position, new_position)`。
  - `ReadmeOptions(max_files=5000, max_depth=64, readme_path=None, max_title_bytes=262144)`。
  - `ReadmeUndetermined(item, reason)`、`ReadmeDegraded(item, reason)`（字段与健康报告同形，**禁止**从 `health.models` 导入，避免 `readme → health` 反向依赖）。
  - `ReadmeReport(status, format_version, scan_root, document_count, demo_project_count, demo_project_suspected_count, readme_found, readme_path, toc_block_found, toc_marker_kind, index, index_markdown, replacement_block, diffs=(), undetermined=(), degraded=(), warnings=(), scanned_at="", duration_ms=0)`。
  - `empty_index() -> TocIndex`
  - `sort_diffs(diffs: Sequence[ReadmeDiff]) -> tuple[ReadmeDiff, ...]`
  - `validate_readme_report(report: ReadmeReport) -> tuple[str, ...]`
- **验收标准**：
  - [ ] 所有 dataclass 使用 `@dataclass(frozen=True, slots=True)`，默认值不写可变对象。
  - [ ] `empty_index()` 返回两个固定分区（`文档索引`、`Demo 工程`），条目为空，`root_readme_path=None`。
  - [ ] `sort_diffs()` 按 `新增 → 删除 → 移动 → 标题变化` 固定顺序，再按 `path` 升序。
  - [ ] `validate_readme_report()` 返回中文问题列表；空列表表示契约成立。
  - [ ] `ReadmeReport` 的 JSON 形状与 `design.md` 2.8.5 一致，不出现 `health.models` 类型。
  - [ ] 导入仅 `from __future__`、`from dataclasses`、`from enum`、`from typing`；无第三方、无 health 导入。
- **路径回报**：实际写入 `backend/app/readme/models.py`。

## 主任务 6：文档标题提取与 Demo 识别 `backend/app/readme/scanner.py`

- **交付物**：`backend/app/readme/scanner.py`。
- **前置**：主任务 2、3、4、5。
- **输入**：`design.md` 2.2.1（12）、2.8.1、2.8.2；`spec.md` 7.1、7.2；`demo-repo/` 结构。
- **输出**：`DocEntry` 列表、`DemoScanResult`（已确认/疑似/无法判定）、警告。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - 常量：`DOC_SUFFIX: str = ".md"`、`MAX_TITLE_LENGTH: int = 200`、`SOURCE_SUFFIXES: frozenset[str]`、`STRONG_ENTRY_FILES: frozenset[str]`、`STRONG_BUILD_FILES: frozenset[str]`、`DEMO_HINT_WORDS: tuple[str, ...] = ("demo", "example", "sample", "tutorial")`、`DEMO_EXCLUDED_DIRS: frozenset[str]`、`TEST_FILE_PATTERNS: tuple[str, ...] = ("test_*.py", "*_test.py", "*.test.js", "*.spec.js")`。
  - `extract_markdown_title(text: str, file_path: str) -> TitleResult`
  - `scan_documents(root: str | Path, walk_result: WalkResult | None = None, options: ReadmeOptions | None = None, warnings: list[str] | None = None) -> tuple[DocEntry, ...]`
  - `scan_demo_projects(root: str | Path, walk_result: WalkResult | None = None, options: ReadmeOptions | None = None, warnings: list[str] | None = None) -> DemoScanResult`
  - `classify_demo_directory(relative_dir: str, entry_names: Sequence[str]) -> tuple[str, tuple[str, ...]]`（返回 `confirmed`/`suspected`/`undetermined`/`none` + 证据）。
  - `is_test_file(name: str) -> bool`
- **验收标准**：
  - [ ] 标题提取严格按 S1～S9：统一换行 → 跳过已闭合 YAML front matter（未闭合按普通内容并警告）→ HTML 注释内不识别 → 围栏代码块（```/~~~）内不识别 → 行首 0～3 空格 + 1～6 个 `#` + 空格/行尾才识别 → 去闭合 `#`、折叠空白、去行内反引号 → 首个 H1 优先 → 无 H1 回退文件名。
  - [ ] `#标题`（无空格）不识别；H2 出现在 H1 之前仍取 H1；标题超过 200 字符截断并 `truncated=True`。
  - [ ] 0 字节/纯空白/编码不可读回退文件名，并分别给出正确 `title_source` 与中文警告。
  - [ ] `scan_documents()` 只处理 `.md`，`path` 为相对仓库根 `/` 分隔，按 `path` 升序。
  - [ ] Demo 识别只统计目录**直接子文件**，根目录不作为候选；排除目录含 `tests`、`test`、`assets`、`docs`、`notes` 与技术目录。
  - [ ] 强证据：入口文件或构建/依赖文件命中即 `confirmed`；弱证据：≥2 源码 + README，或 ≥1 源码且目录名/文件名含提示词 → `suspected`；单源码且无 README/入口/构建/提示 → `undetermined` 并给出中文原因。
  - [ ] `test_*.py`、`*_test.py`、`*.test.js`、`*.spec.js` 不计入源码文件数。
  - [ ] `demo-repo/lab/uart`（`uart_demo.c` + `UART Demo-v2.C`）识别为疑似；`demo-repo/backend/app`（`example_config.py`）识别为疑似；`assets/docs/notes/backend/tests` 不进入 Demo 分区；不得输出「已确认/这是 Demo」的确定结论。
  - [ ] 读取异常、标题截断、编码失败均进入 `warnings`，不中断其它文档。
  - [ ] 不缓存全文；每个文件读取后即释放。
  - [ ] 导入：`import fnmatch`、`import re` 用模块形式；相对导入 `..shared.repo_walk`、`..shared.text_io`、`.models`；无 health 导入。
- **路径回报**：实际写入 `backend/app/readme/scanner.py`。

## 主任务 7：健康报告数据契约、映射与排序 `backend/app/health/models.py`

- **交付物**：`backend/app/health/models.py`。
- **前置**：主任务 5、6（仅需 `readme.models` 的 Demo 统计类型）。
- **并行组**：P2。
- **输入**：`design.md` 2.2.1（5）、2.3.2、2.7；`spec.md` 5.5、6.1～6.5。
- **输出**：健康报告全部冻结结构、级别映射、排序与一致性校验。
- **需要实现的类型与签名（与 design 2.2.1 一致）**：
  - 枚举：`HealthStatus(Enum)`（`OK="正常"`、`PARTIAL_DEGRADED="部分降级"`、`INPUT_ERROR="输入错误"`）；`RiskLevel(Enum)`（`HIGH="高风险"`、`SUGGESTION="建议"`）。
  - 常量：`RISK_BY_LEVEL: Mapping[IssueLevel, RiskLevel]`、`SOURCE_MODULE_BY_PREFIX: Mapping[str, str]`、`DEGRADED_ORDER: tuple[str, ...]`。
  - `ScanMeta(format_version="1.0", scan_root="<repo>", file_count=0, markdown_count=0, code_file_count=0, demo_project_count=0, demo_project_suspected_count=0, scanned_at="", duration_ms=0)`。
  - `HealthOptions(zombie_days=365, git_mode="auto", max_files=5000, max_depth=64, enable_zombie=True, now=None)`。
  - `HealthIssue(rule_id, source_module, risk_level, line_no, message, suggestion, excerpt)`；别名 `HealthFinding = HealthIssue`。
  - `HealthFileEntry(file_path, risk_level, issue_count, findings=())`。
  - `ZombieCandidate(file_path, basis, last_activity, idle_days, reference_count, risk_level, suggestion)`。
  - `UndeterminedItem(item, reason)`、`DegradedItem(item, reason)`。
  - `HealthSummary(issue_count, must_fix_count, suggestion_count, zombie_candidate_count, undetermined_count, skipped_file_count, degraded_count)`。
  - `HealthReport(status, meta, summary, files=(), zombie_candidates=(), undetermined=(), degraded=(), warnings=())`。
  - `risk_for_level(level: IssueLevel) -> RiskLevel`
  - `source_module_for_rule(rule_id: str) -> str`
  - `resolve_options(options: HealthOptions | None) -> tuple[HealthOptions, tuple[str, ...]]`
  - `sort_issues(issues: Sequence[HealthIssue]) -> tuple[HealthIssue, ...]`
  - `sort_files(entries: Sequence[HealthFileEntry]) -> tuple[HealthFileEntry, ...]`
  - `sort_zombies(items: Sequence[ZombieCandidate]) -> tuple[ZombieCandidate, ...]`
  - `sort_undetermined(items: Sequence[UndeterminedItem]) -> tuple[UndeterminedItem, ...]`
  - `sort_degraded(items: Sequence[DegradedItem]) -> tuple[DegradedItem, ...]`
  - `build_summary(*, files, zombies, undetermined, degraded, skipped_file_count) -> HealthSummary`
  - `validate_health_report(report: HealthReport) -> tuple[str, ...]`
- **验收标准**：
  - [ ] `必须修改 → 高风险`、`优化建议 → 建议` 一对一映射；未知级别不猜测、不改写。
  - [ ] `rule_id` 前缀映射：`naming-`→命名与目录检查、`code-`→代码检查、`link-`→链接检查、`sens-`→敏感信息与大文件检查；未知前缀→`报告` 并产生警告。
  - [ ] `resolve_options()` 对 `zombie_days` 不在 30～3650 时回退 365，并返回中文警告；`max_files` 越界由 CLI 拦截。
  - [ ] `sort_issues()`：高风险先于建议 → 有行号先于无行号 → 行号升序 → `rule_id` → `message`。
  - [ ] `sort_files()` 按 `file_path` Unicode 码点升序；`sort_zombies()` 按 `file_path`；`sort_undetermined()` 按 `(item, reason)`；`sort_degraded()` 按 `DEGRADED_ORDER` 再按 `reason`，并做 `(item, reason)` 去重。
  - [ ] `build_summary()` 满足 7 条不变量：`issue_count == must_fix + suggestion`、计数等于实际条目数、`files[*].issue_count == len(findings)`。
  - [ ] `validate_health_report()` 返回中文问题列表；不一致时调用方可置 `部分降级`。
  - [ ] 全部 dataclass 冻结且 `slots=True`；`ScanMeta` 可扁平化到报告顶层。
  - [ ] 导入：`from __future__`、`from dataclasses`、`from enum`、`from typing`、`from ..core.rules.common.models`；`import datetime` 用模块形式。
- **路径回报**：实际写入 `backend/app/health/models.py`。

## 主任务 8：僵尸候选三条件判定 `backend/app/health/zombie.py`

- **交付物**：`backend/app/health/zombie.py`。
- **前置**：主任务 3、4、7。
- **并行组**：P2（与主任务 13、14、15 并行）。
- **输入**：`design.md` 2.2.1（7）、2.6.1～2.6.7；`spec.md` 5.4；`WalkResult.files`、`HealthOptions`。
- **输出**：`ZombieResult`（候选、无法判定、降级、mtime 可信度、git 使用标记、引用完整性）。
- **需要实现的类型与签名（与 design 2.2.1 一致）**：
  - 常量：`DEFAULT_ZOMBIE_DAYS=365`、`MIN_ZOMBIE_DAYS=30`、`MAX_ZOMBIE_DAYS=3650`、`BATCH_WINDOW_SECONDS=3600.0`、`BATCH_RATIO=0.8`、`GIT_TIMEOUT_PER_FILE=2.0`、`GIT_TOTAL_BUDGET=30.0`、`GENERIC_BASENAMES: frozenset[str]`、`REFERENCE_SUFFIXES: frozenset[str]`、`DEMO_HINT_WORDS: tuple[str, ...]`。
  - `GitActivity(available, timestamp, reason)`。
  - `GitBudget(deadline)`，方法 `remaining() -> float`。
  - `ReferenceResult(referenced, complete, unreadable_count, unreadable_items)`。
  - `ZombieResult(candidates=(), undetermined=(), degraded=(), mtime_credible=True, git_used=False, reference_complete=True)`。
  - `detect_zombies(root: str | Path, files: Sequence[WalkedFile], options: HealthOptions, text_reader: Callable[[WalkedFile], str | None] | None = None) -> ZombieResult`
  - `collect_reference_counts(root: str | Path, candidates: Sequence[str], files: Sequence[WalkedFile], *, reader: Callable[[WalkedFile], str | None] | None = None) -> ReferenceResult`
  - `get_git_last_commit(root: str | Path, relative_path: str, *, timeout_s: float = GIT_TIMEOUT_PER_FILE, budget: GitBudget | None = None) -> GitActivity`
  - `is_git_work_tree(root: str | Path) -> bool`
  - `evaluate_mtime_credibility(files: Sequence[WalkedFile]) -> tuple[bool, str | None]`
  - `is_generic_basename(relative_path: str) -> bool`
  - `zombie_exemption_reason(relative_path: str) -> str | None`
  - `compute_idle_days(last_activity_ts: float, now_ts: float) -> int`
  - `format_activity_date(last_activity_ts: float) -> str`
- **验收标准**：
  - [ ] 判定式严格为「引用可靠 且 引用=0 且 时间依据可信 且 空闲天数 ≥ `zombie_days` 且 非豁免」→ 候选；任一条件不满足按 U1～U8 输出无法判定/降级/不输出。
  - [ ] 候选字段完整：`basis` 仅 `git`/`mtime`、`last_activity` 为 UTC `YYYY-MM-DD`、`idle_days >= zombie_days`、`reference_count=0`、`risk_level=建议`、建议文案固定为人工确认文案。
  - [ ] Git 命令为只读参数列表：`git --no-pager --no-optional-locks -C <root> log -1 --format=%ct -- <relative_path>`；`shell=False`、`capture_output=True`、单文件超时 ≤2 秒、总预算 30 秒；环境追加 `GIT_TERMINAL_PROMPT=0`、`GIT_OPTIONAL_LOCKS=0`、`GIT_CONFIG_NOSYSTEM=1`。
  - [ ] Git 不可用、非工作区、非零返回码、`FileNotFoundError`、`TimeoutExpired`、`OSError`、预算耗尽均转为中文降级原因，不抛异常、不阻塞巡检。
  - [ ] 禁止任何写命令与远程命令（`add/commit/checkout/clean/fetch/pull/ls-remote` 等）。
  - [ ] 引用扫描：候选 needles = 相对路径 + basename，去重后单正则扫描；只取「是否被引用」布尔结论；候选自身命中不计；候选为 0 时不读正文；逐文件读取后释放。
  - [ ] 引用扫描范围限定 `REFERENCE_SUFFIXES` 且非二进制；任一文件不可读置 `complete=False` 并统计数量；此时所有引用为 0 的候选转无法判定。
  - [ ] mtime 可信度：3600 秒窗口内最大文件数 / 总数 ≥ 0.8 且总数 ≥2 → 不可信，原因含「批量检出」；0/1 文件视为可信。
  - [ ] 豁免与无法判定：通用名/入口/构建文件 →「入口或配置文件不适用僵尸判定」；路径含 demo/example/sample/tutorial →「示例文件不参与僵尸判定」；`.env`/`.env.*`/`.git*` 配置类同入口类；弱信号（体积、扩展名、目录名、命名风格）一律不参与判定。
  - [ ] 时间基准优先 `HealthOptions.now`，否则 UTC 当前时间；`idle_days` 向下取整且 ≥0；同一 `now` 下结果确定。
  - [ ] 只 `stat`/读取，不修改 mtime、不移动/删除文件；无网络调用。
  - [ ] 导入：`import datetime`、`import os`、`import re`、`import subprocess` 用模块形式；相对导入 `..core.rules.common.config`、`..shared.repo_walk`、`..shared.text_io`、`.models`；禁止导入四个检查模块。
- **路径回报**：实际写入 `backend/app/health/zombie.py`。

## 主任务 9：全仓巡检编排与报告映射 `backend/app/health/service.py`

- **交付物**：`backend/app/health/service.py`。
- **前置**：主任务 6、7、8。
- **输入**：`design.md` 2.2.1（6）、2.5.1～2.5.4、2.7.6；`spec.md` 4.3、5、6、11.1.2。
- **输出**：`HealthReport`、退出码；`run_check()` 唯一调用点。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - 常量：`MAX_DETAILED_DEGRADED: int = 50`、`HEALTH_FORMAT_VERSION: str = "1.0"`。
  - `run_health_check(repo_root: str | Path | None = None, options: HealthOptions | None = None, rule_config: RuleConfig | None = None) -> HealthReport`
  - `exit_code_for(report: HealthReport) -> int`
  - `resolve_repo_root(repo_root: str | Path | None = None) -> Path`
  - `build_manifest(walk_result: WalkResult) -> str`
  - `map_file_entries(check_report: CheckReport, walk_result: WalkResult) -> tuple[HealthFileEntry, ...]`
  - `collect_degraded(*, walk_result: WalkResult, check_report: CheckReport | None, zombie_result: ZombieResult | None, demo_result: DemoScanResult | None, extra: Sequence[tuple[str, str]] = ()) -> tuple[DegradedItem, ...]`
  - `make_report(*, status: HealthStatus, meta: ScanMeta, files: Sequence[HealthFileEntry], zombies: Sequence[ZombieCandidate], undetermined: Sequence[UndeterminedItem], degraded: Sequence[DegradedItem], warnings: Sequence[str], skipped_file_count: int) -> HealthReport`
  - `input_error_report(reason: str, *, scan_root: str = "<repo>", duration_ms: int = 0) -> HealthReport`
- **验收标准**：
  - [ ] 正常仓库中 `run_check()` 调用次数恰好为 1；空仓库调用 0 次；文件数超限调用 0 次。
  - [ ] 调用参数只包含内存清单、仓库根、`RuleConfig`/`None`；不逐文件调用四模块、不导入四模块。
  - [ ] 清单只含遍历确认可纳入的文件，状态固定 `M`，路径相对、`/` 分隔、无 `..`、无盘符；空清单不调用 `run_check()`。
  - [ ] 映射：`CheckReport.status` 三态映射；`files` 仅保留有 findings 的组；`file_path` 原样；文件级风险取组内最高；`issue_count=len(findings)`；`Finding` 五个字段原样搬运，不二次截断/脱敏/改级。
  - [ ] 统计：`must_fix_count`、`suggestion_count`、`issue_count` 直接取阶段 1 值并与文件条目重算比对；不一致置部分降级。
  - [ ] 降级：`degraded_modules` 名称与中文原因逐字透传；`skip_reason` 计入 `skipped_file_count`，明细最多 50 条，超出聚合为一条；`unparsed_lines` 非空合并为「清单解析」降级；遍历跳过明细进入 `degraded`，不重复计入阶段 1 跳过数。
  - [ ] `run_check()` 外层 `try/except Exception`：异常时 `部分降级` + `DegradedItem("检查入口", ...)` + 统计为 0 的报告，不崩溃、不输出堆栈。
  - [ ] `meta`：`scan_root` 只取末段或 `<repo>`；文件/Markdown/代码计数来自 `WalkResult`；Demo 已确认/疑似来自 `scan_demo_projects()`；`scanned_at` 为 UTC ISO 8601；`duration_ms` 为 `perf_counter()` 差值且 ≥0。
  - [ ] `exit_code_for()` 优先级 `2 > 3 > 1 > 0`：输入错误 2；有降级 3；有高风险 1；否则 0；僵尸候选与无法判定本身不触发 1/3（无法判定仅在降级时随 3）。
  - [ ] 根校验失败返回 `INPUT_ERROR` 报告，中文原因，退出码 2；仓库根含工具自身 `backend/app` 时同理。
  - [ ] 全流程只读、无网络、无端口；不写 `demo-repo`。
  - [ ] 导入：`from __future__`、`from pathlib`、`from typing`、`from time`、`..core.rules.common.config`、`..core.rules.common.models`、`..core.rules.engine`、`..readme.models`、`..readme.scanner`、`..shared.repo_walk`、`..shared.text_io`、`.models`、`.zombie`；`import datetime` 模块形式。
- **路径回报**：实际写入 `backend/app/health/service.py`。

## 主任务 10：健康报告 text/JSON 渲染 `backend/app/health/render.py`

- **交付物**：`backend/app/health/render.py`。
- **前置**：主任务 7。
- **并行组**：P3。
- **输入**：`design.md` 2.2.1（8）、2.7.1～2.7.5；`spec.md` 6.6。
- **输出**：中文摘要与可解析 JSON。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `render_health_text(report: HealthReport) -> str`
  - `health_to_dict(report: HealthReport) -> dict[str, object]`
  - `health_to_json(report: HealthReport) -> str`
- **验收标准**：
  - [ ] text 顺序固定：总览 → 高风险 → 建议 → 僵尸候选 → 无法判定 → 降级项 → 警告；开头明确高风险数量与「请先处理高风险项」。
  - [ ] 各段空状态文案完整：`未发现高风险问题。`、`未发现建议项。`、`未发现僵尸候选。`、`无无法判定项。`、`本次巡检未发生降级。`；无警告时省略警告段。
  - [ ] 输入错误只输出「输入存在错误，本次巡检未执行：<中文原因>」；超限输出「超过上限」+ 降级说明 + 「请缩小巡检范围后重试」；空仓库输出「仓库内未发现可巡检文件」+ 全 0 统计。
  - [ ] JSON 顶层字段顺序与 2.7.1 完全一致，`meta` 扁平化；`ensure_ascii=False`、`indent=2`；中文不转义；空列表为 `[]` 不是 `null`。
  - [ ] 不出现绝对路径、盘符、UNC、用户主目录、英文堆栈、额外风险等级。
  - [ ] 文本与 JSON 对同一 `HealthReport` 均可生成，且内容自洽。
  - [ ] 导入：`from __future__`、`from typing`、`.models`；`import json` 模块形式。
- **路径回报**：实际写入 `backend/app/health/render.py`。

## 主任务 11：健康巡检 CLI `backend/app/health/cli.py`

- **交付物**：`backend/app/health/cli.py`。
- **前置**：主任务 3、4、7、9、10。
- **并行组**：P4（可与主任务 16 并行）。
- **输入**：`design.md` 2.2.1（9）、2.9.1；`spec.md` 8.1、8.2.1、8.3。
- **输出**：`python -m app.health.cli` 入口、参数解析、输出与退出码。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `build_arg_parser() -> argparse.ArgumentParser`
  - `parse_health_options(args: argparse.Namespace) -> tuple[HealthOptions, tuple[str, ...]]`
  - `validate_output_path(root: str | Path, output: str | Path) -> str | None`
  - `main(argv: Sequence[str] | None = None) -> int`
- **验收标准**：
  - [ ] 参数完整：`--repo`（默认解析 `../demo-repo` 后 `demo-repo`）、`--format text|json`（默认 text）、`--output`、`--zombie-days`（默认 365，30～3650，非法回退并警告）、`--git auto|on|off`（默认 auto，非法由 argparse 返回 2）、`--max-files`（默认 5000，30～50000，越界返回 2）、`--config`（透传 `build_config(config_file=...)`，读取/JSON 失败用默认配置 + 警告）、`--debug`。
  - [ ] `validate_output_path()`：真实路径必须在仓库根之外；已存在目录返回中文错误；不得写 README/仓库内任意文件。
  - [ ] stdout 只输出一份报告（text 或 JSON），末尾单个换行；`--output` 不抑制 stdout；调试信息只进 stderr。
  - [ ] 退出码 `2 > 3 > 1 > 0`，与 `health.service.exit_code_for()` 一致；argparse 参数错误返回 2。
  - [ ] 整体 `try/except Exception`：中文提示「全仓健康巡检执行异常，未能完成，请稍后重试。」+ 退出码 3；仅 `--debug` 输出英文堆栈到 stderr。
  - [ ] 不包装/不回调阶段 1 `engine.main()`；不新增路由、不启动服务、不监听端口。
  - [ ] 帮助文案为中文，包含全部参数与默认值。
  - [ ] 导入：`from __future__`、`from argparse`、`from pathlib`、`from typing`、`..core.rules.common.config`、`..shared.repo_walk`、`.models`、`.render`、`.service`；`import sys`、`import traceback` 模块形式。
- **路径回报**：实际写入 `backend/app/health/cli.py`。

## 主任务 12：health 包公共导出 `backend/app/health/__init__.py`

- **交付物**：`backend/app/health/__init__.py`。
- **前置**：主任务 7、9。
- **并行组**：P3。
- **输入**：`design.md` 2.2.1（4）。
- **输出**：仅再导出，不含逻辑。
- **需要实现的公开符号**：
  - `run_health_check`、`exit_code_for`
  - `HealthReport`、`HealthOptions`、`HealthStatus`、`HealthSummary`、`HealthIssue`、`ZombieCandidate`、`UndeterminedItem`、`DegradedItem`、`ScanMeta`
  - `__all__` 覆盖上述符号。
- **验收标准**：
  - [ ] 仅包标记、相对导入与 `__all__`，无逻辑、无副作用。
  - [ ] `from app.health import run_health_check, HealthReport, HealthOptions` 可成功。
- **路径回报**：实际写入 `backend/app/health/__init__.py`。

---

## 4. README 索引、对比与 CLI

## 主任务 13：目录索引构建与片段渲染 `backend/app/readme/index.py`

- **交付物**：`backend/app/readme/index.py`。
- **前置**：主任务 5、6。
- **并行组**：P2（可与主任务 7、14、15 并行）。
- **输入**：`design.md` 2.2.1（13）、2.8.3；`spec.md` 7.3。
- **输出**：`TocIndex` 与索引 Markdown 片段。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `build_index(documents: Sequence[DocEntry], demos: DemoScanResult | Sequence[DemoProject], anchors: Mapping[str, str] | None = None) -> TocIndex`
  - `render_index_markdown(index: TocIndex, with_markers: bool = False) -> str`
  - `render_link_target(path: str, is_directory: bool = False) -> str`
  - `anchor_slug(title: str) -> str`
- **验收标准**：
  - [ ] 固定两个分区：`文档索引`、`Demo 工程`；任一为空输出标题 + `（无）`，不省略分区。
  - [ ] 文档分区：目录项先于文档项；目录项仅在存在直接/间接文档时出现；空目录不生成条目；同层各按 `path` Unicode 码点升序。
  - [ ] 根 README 标记为 `title="根 README"`、`kind="document"`、`link="README.md"`、`anchor=None`。
  - [ ] 文档项 `depth = path 段数 - 1`、`link=相对路径`、`anchor=None`、`confidence=None`。
  - [ ] Demo 分区：`confirmed` 在前、`suspected` 在后，各自按 `path` 升序；`path` 以 `/` 结尾；疑似项标题追加 `（疑似，待确认）`。
  - [ ] 相对路径：无绝对路径、无 `\`；含空格用 `(<路径>)` 尖括号；中文原样不 percent-encode；目录链接保留尾 `/`。
  - [ ] 锚点：仅对现有 README 存在的同名标题生成；`anchor_slug()` 按小写 → 空格换 `-` → 去非字母/数字/中文/连字符/下划线 → 合并连续 `-` → 重名 `-1/-2`；禁止凭空生成。
  - [ ] 同一 `path` 只保留第一次出现并产生中文警告；标题相同路径不同不合并，链接文本追加路径末段区分。
  - [ ] `with_markers=False` 默认不带 TOC 标记；`True` 时输出 `<!-- TOC -->` 与 `<!-- /TOC -->`。
  - [ ] `render_index_markdown()` 是替换片段的唯一正文来源，保证「片段正文 == 索引」。
  - [ ] 导入：`from __future__`、`from typing`、`.models`；`import re` 模块形式。
- **路径回报**：实际写入 `backend/app/readme/index.py`。

## 主任务 14：README 定位、目录区块识别与差异 `backend/app/readme/compare.py`

- **交付物**：`backend/app/readme/compare.py`。
- **前置**：主任务 5、6。
- **并行组**：P2（可与主任务 7、13、15 并行）。
- **输入**：`design.md` 2.2.1（14）、2.8.4；`spec.md` 7.4、7.5；现有 `demo-repo/assets/README.md` 等。
- **输出**：README 路径、`TocBlock`、四类差异、替换片段、路径校验。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `locate_readme(root: str | Path, readme_path: str | Path | None = None) -> Path | None`
  - `locate_toc_block(text: str) -> TocBlock | None`
  - `parse_toc_entries(block: TocBlock) -> tuple[TocEntryRef, ...]`
  - `collect_heading_anchors(text: str) -> dict[str, str]`
  - `diff_toc(block: TocBlock | None, index: TocIndex) -> tuple[ReadmeDiff, ...]`
  - `render_replacement_block(index: TocIndex, block: TocBlock | None = None) -> str`
  - `validate_readme_path(root: str | Path, candidate: str | Path) -> tuple[Path | None, str | None]`
- **验收标准**：
  - [ ] `locate_readme()` 默认依次尝试 `README.md`、`readme.md`，大小写不敏感；显式路径必须在仓库根内且为文件；未找到返回 `None`。
  - [ ] 目录区块识别三种方式：`<!-- TOC -->`/`<!-- /TOC -->`、`<!-- BEGIN TOC -->`/`<!-- END TOC -->`（大小写与前后空白容错）、标题 `#{1,3}` + `目录`/`文档目录`/`Table of Contents`/`Contents`（结束于下一个同级或更高级 ATX 标题之前）。
  - [ ] `TocBlock` 行号 0 基、`end_line` 含端点、保留原始行；未识别返回 `None`。
  - [ ] `parse_toc_entries()` 只解析 Markdown 行内链接；跳过 `http/https/mailto/#` 与绝对路径；去尖括号、去 `#anchor`、去 `./`、`\`→`/`；目录项保留尾 `/` 作为键标记；`depth` 按前导空格/2（制表符按 2 空格）计算；`position` 1 基。
  - [ ] `diff_toc()` 只比较 `path` 与 `title`（去掉 `（疑似，待确认）` 等展示后缀）；输出新增/删除/移动/标题变化；同一路径同时移动与标题变化输出两条；排序为固定类型顺序再按 `path` 升序。
  - [ ] `render_replacement_block()`：`TOC`/`BEGIN_TOC` 沿用相同标记；`heading` 保留原目录标题行；未识别输出纯索引正文；正文与 `render_index_markdown()` 逐字一致，不含索引外条目。
  - [ ] `validate_readme_path()` 越界/不可读返回中文错误；`--output` 指向 README 的校验由 CLI 负责。
  - [ ] 只读：仅读取 README，不写回、不改 mtime/权限/编码；无 `--write/--apply`。
  - [ ] 导入：`from __future__`、`from pathlib`、`from typing`、`..shared.repo_walk`、`..shared.text_io`、`.models`；`import re` 模块形式。
- **路径回报**：实际写入 `backend/app/readme/compare.py`。

## 主任务 15：README 报告 text/JSON 渲染 `backend/app/readme/render.py`

- **交付物**：`backend/app/readme/render.py`。
- **前置**：主任务 5。
- **并行组**：P3。
- **输入**：`design.md` 2.2.1（16）、2.8.5、2.9.2。
- **输出**：中文摘要与 `ReadmeReport` JSON。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `render_readme_text(report: ReadmeReport) -> str`
  - `readme_to_dict(report: ReadmeReport) -> dict[str, object]`
  - `readme_to_json(report: ReadmeReport) -> str`
- **验收标准**：
  - [ ] text 顺序：文档/Demo 统计 → 文档索引 → Demo 工程 → 差异 → 替换片段 → 无法判定/降级/警告。
  - [ ] 无差异时输出明确中文空状态；无 README 或区块缺失时输出对应无法判定原因与「需人工选择插入位置」提示。
  - [ ] JSON 字段与 2.8.5 一致：顶层 `format_version/status/scan_root/document_count/demo_project_count/demo_project_suspected_count/readme_found/readme_path/toc_block_found/toc_marker_kind/index/index_markdown/replacement_block/diffs/undetermined/degraded/warnings/scanned_at/duration_ms`。
  - [ ] `ensure_ascii=False`、`indent=2`；空列表为 `[]`；不出现绝对路径、英文堆栈。
  - [ ] 替换片段只作为文本输出，不写 README。
  - [ ] 导入：`from __future__`、`from typing`、`.models`；`import json` 模块形式。
- **路径回报**：实际写入 `backend/app/readme/render.py`。

## 主任务 16：README 扫描编排与报告组装 `backend/app/readme/service.py`

- **交付物**：`backend/app/readme/service.py`。
- **前置**：主任务 6、13、14、15。
- **并行组**：P4（可与主任务 11 并行）。
- **输入**：`design.md` 2.2.1（15）、2.1.3（2）、2.8.4；`spec.md` 7.4.1、7.5、8.3。
- **输出**：`ReadmeReport` 与退出码。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - 常量：`README_FORMAT_VERSION: str = "1.0"`。
  - `run_readme_scan(repo_root: str | Path | None = None, options: ReadmeOptions | None = None) -> ReadmeReport`
  - `exit_code_for(report: ReadmeReport) -> int`
  - `input_error_report(reason: str, *, scan_root: str = "<repo>", duration_ms: int = 0) -> ReadmeReport`
- **验收标准**：
  - [ ] 编排顺序：根校验 → `walk_repository()` → `scan_documents()` → `scan_demo_projects()` → `locate_readme()` → `collect_heading_anchors()` → `build_index()` → `render_index_markdown()` → 区块识别/差异/替换片段 → 报告。
  - [ ] README 未找到：`readme_found=False`、`readme_path=None`、不做差异、`undetermined` 含「仓库根未找到 README」、仍输出完整索引片段。
  - [ ] 区块未识别：`toc_block_found=False`、`toc_marker_kind=None`、不做差异、`undetermined` 含「未识别现有目录区块」、仍输出完整替换片段。
  - [ ] 报告统计：`document_count`、`demo_project_count`（已确认）、`demo_project_suspected_count`（疑似）正确；疑似不计入已确认。
  - [ ] 状态：无差差异无无法判定为 `正常`；有无法判定/区块缺失/执行异常为 `部分降级`；根/README 非法为 `输入错误`。
  - [ ] `exit_code_for()`：`2 > 3 > 1 > 0`；至少一条差异为 1；存在无法判定/区块缺失/异常为 3；否则 0。
  - [ ] `scanned_at` UTC ISO 8601、`duration_ms >= 0`；不写 README、不写被巡检仓库、无网络、无端口。
  - [ ] 不导入 `health`、不导入 `app.api`、不导入四模块。
  - [ ] 导入：`from __future__`、`from pathlib`、`from time`、`from typing`、`..shared.repo_walk`、`..shared.text_io`、`.compare`、`.index`、`.models`、`.render`、`.scanner`；`import datetime` 模块形式。
- **路径回报**：实际写入 `backend/app/readme/service.py`。

## 主任务 17：README CLI `backend/app/readme/cli.py`

- **交付物**：`backend/app/readme/cli.py`。
- **前置**：主任务 3、4、14、15、16。
- **并行组**：P5（可与主任务 18 并行）。
- **输入**：`design.md` 2.2.1（17）、2.9.2；`spec.md` 8.1、8.2.2、8.3。
- **输出**：`python -m app.readme.cli` 入口、参数、输出、退出码。
- **需要实现的函数签名（与 design 2.2.1 一致）**：
  - `build_arg_parser() -> argparse.ArgumentParser`
  - `parse_readme_options(args: argparse.Namespace) -> tuple[ReadmeOptions, tuple[str, ...]]`
  - `validate_output_path(root: str | Path, output: str | Path, readme_path: str | Path | None) -> str | None`
  - `main(argv: Sequence[str] | None = None) -> int`
- **验收标准**：
  - [ ] 参数完整：`--repo`、`--format text|json`（默认 text）、`--readme`（默认自动查找，必须在仓库根内且为文件）、`--output`（仓库外且不得等于 README）、`--max-files`（默认 5000，30～50000）、`--debug`。
  - [ ] `validate_output_path()` 拒绝仓库内路径、拒绝等于 README、拒绝已存在目录；违规返回中文错误且不写盘。
  - [ ] `--readme` 越界/不可读返回退出码 2。
  - [ ] stdout 只输出一份报告；text 模式包含统计、索引、Demo、差异、替换片段、无法判定/降级/警告；JSON 模式输出完整 `ReadmeReport`。
  - [ ] 退出码 `2 > 3 > 1 > 0`，与 `readme.service.exit_code_for()` 一致。
  - [ ] 整体异常捕获：中文提示 + 退出码 3；仅 `--debug` 输出堆栈到 stderr。
  - [ ] 不提供 `--write`/`--apply`；不写 README、不包装阶段 1 CLI、不启动服务。
  - [ ] 帮助文案为中文，包含全部参数与默认值。
  - [ ] 导入：`from __future__`、`from argparse`、`from pathlib`、`from typing`、`..shared.repo_walk`、`.compare`、`.models`、`.render`、`.service`；`import sys`、`import traceback` 模块形式。
- **路径回报**：实际写入 `backend/app/readme/cli.py`。

## 主任务 18：readme 包公共导出 `backend/app/readme/__init__.py`

- **交付物**：`backend/app/readme/__init__.py`。
- **前置**：主任务 5、16。
- **并行组**：P6。
- **输入**：`design.md` 2.2.1（10）。
- **输出**：仅再导出，不含逻辑。
- **需要实现的公开符号**：
  - `run_readme_scan`、`exit_code_for`
  - `ReadmeReport`、`ReadmeOptions`、`ReadmeStatus`、`TocIndex`、`TocItem`、`ReadmeDiff`
  - `__all__` 覆盖上述符号。
- **验收标准**：
  - [ ] 仅包标记、相对导入与 `__all__`，无逻辑、无副作用。
  - [ ] `from app.readme import run_readme_scan, ReadmeReport` 可成功。
- **路径回报**：实际写入 `backend/app/readme/__init__.py`。

---

## 5. 新增测试文件（9 个，全部 unittest）

> 通用验收：每个文件只使用 `unittest`、`unittest.mock`、`tempfile`、`pathlib`、`json` 等标准库；不使用 pytest；不修改既有测试；测试数据写入临时目录，不写入 `demo-repo`；符号链接用例在 `PermissionError/OSError` 时 `skipTest`；网络用例用 `patch("socket.socket", side_effect=AssertionError)`；每个文件可被 `unittest discover` 发现。

## 主任务 19：`backend/tests/test_repo_walk.py`

- **前置**：主任务 4。
- **输入**：`app.shared.repo_walk`、临时目录夹具。
- **输出**：遍历与路径安全测试，共 18 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| RW-01 | 默认根优先 `../demo-repo` | 临时 `backend/` 下存在 `../demo-repo` 与 `demo-repo` | 返回 `../demo-repo`；删除后回落 `demo-repo`；都不存在抛中文 `RootValidationError` |
| RW-02 | 显式根与递归 | 3 层嵌套、5 个文件 | `files` 含全部文件，按 `path` 升序，`directory_count` 正确 |
| RW-03 | 跳过技术目录 | `.git`、`node_modules`、`__pycache__`、`venv`、`dist`、`x.egg-info` 各放 1 文件 | 均不出现在 `files` |
| RW-04 | 隐藏文件纳入 | `.env`、`.gitignore` | 出现在 `files`，不因 `.` 前缀跳过 |
| RW-05 | 隐藏目录展开 | `.github/workflows/a.yml` | 被展开并纳入 |
| RW-06 | 深度上限 | `WalkOptions(max_depth=2)`，3 层文件 | 第 3 层不展开，`skipped` 含「深度超限」 |
| RW-07 | 最大文件数 | 5 个文件、`max_files=3` | `exceeded_max_files=True`、`files=()`，无部分清单 |
| RW-08 | 目录符号链接不跟随 | 目录链接指向根外 | 不递归，`skipped` 含「目录符号链接」；无权限时 skipTest |
| RW-09 | 文件符号链接逃逸 | 链接指向根外文件 | `files` 不含，`skipped` 含「符号链接逃逸」 |
| RW-10 | 根内文件符号链接 | 链接指向根内文件 | 以链接相对路径入清单 |
| RW-11 | 路径归一化 | 任意嵌套文件 | 输出无 `\`、无盘符、无 `./` |
| RW-12 | 含空格清单行 | `lab/uart/UART Demo-v2.C` | 单行 `M lab/uart/UART Demo-v2.C`，空格原样保留 |
| RW-13 | 文件名含换行 | 名称含 `\n` | 跳过并记录「文件名包含非法字符」；清单无伪造行 |
| RW-14 | 非法根 | 不存在路径、普通文件路径 | 抛 `RootValidationError`，中文原因 |
| RW-15 | 自扫描拒绝 | 根为工具仓库根（含工具 `backend/app`） | 拒绝，原因含「工具自身源码目录」；`demo-repo` 根不被拒绝 |
| RW-16 | 权限/stat 失败 | patch `os.scandir`/`stat` 抛 `PermissionError` | 该条目跳过，其余文件继续，不崩溃 |
| RW-17 | 编码文件不读内容 | GB18030 编码的 `.md` | 遍历阶段正常入清单，不读取内容、不抛错 |
| RW-18 | 清单安全 | 含 `..`、绝对路径的候选 | 清单无 `..`、无绝对路径，每行以 `M ` 开头 |

- **验收标准**：
  - [ ] 18 个用例全部通过，0 failed / 0 error。
  - [ ] 不写被巡检目录；断言前后文件列表一致。
  - [ ] 仅新增 `backend/tests/test_repo_walk.py`，不改 `test_engine.py`。
- **路径回报**：实际写入 `backend/tests/test_repo_walk.py`。

## 主任务 20：`backend/tests/test_health_service.py`

- **前置**：主任务 9、11。
- **输入**：`app.health.service`、`app.health.cli`、临时仓库、fake `CheckReport`。
- **输出**：巡检复用、映射、只读测试，共 16 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| HS-01 | `run_check` 仅一次 | patch `app.health.service.run_check` | 调用次数 == 1 |
| HS-02 | 空仓库 0 次 | 空目录 | `run_check` 0 次；文件/统计全 0；结构完整；text 含空状态 |
| HS-03 | 计数映射 | 3 个 `.md`、4 个代码、1 个 `.txt`，Demo 已确认/疑似各 1 | `file_count/markdown_count/code_file_count/demo_*` 与夹具一致 |
| HS-04 | 分级映射 | 混合 MUST_FIX/SUGGESTION | `必须修改→高风险`、`优化建议→建议`；文件级取最高 |
| HS-05 | 统计不变量 | 多文件多问题 | 7 条不变量全部成立 |
| HS-06 | 降级透传 | fake `degraded_modules` | 模块名与中文原因逐字进入 `degraded` |
| HS-07 | 跳过计数与聚合 | 60 个 `skip_reason` | `skipped_file_count=60`；明细 50 条 + 1 条聚合 |
| HS-08 | 清单解析降级 | `unparsed_lines` 非空 | `degraded` 含「清单解析」 |
| HS-09 | 引擎异常隔离 | patch `run_check` 抛 `RuntimeError` | `部分降级` + 「检查入口」降级，不崩溃 |
| HS-10 | 只读快照 | 含文本/二进制/Markdown 的临时仓库 | 前后文件列表与 `size+sha256+mtime` 完全一致 |
| HS-11 | 无网络 | patch `socket.socket` 抛 `AssertionError` | 巡检正常返回，不触发 socket |
| HS-12 | `--output` 仓库内拒绝 | `validate_output_path(root, root/"r.json")` | 返回中文错误；CLI 退出码 2，仓库内无新文件 |
| HS-13 | 二进制只做体积检查 | 8 MB `.mp4` | 体积类结论存在；无文本敏感匹配 |
| HS-14 | text/JSON 同源 | 同一 `HealthReport` | `render_health_text` 与 `health_to_json` 均成功，JSON 可解析 |
| HS-15 | 输入错误 | 根含工具自身 `backend/app` | `status=输入错误`、退出码 2、`run_check` 0 次 |
| HS-16 | 文件数超限 | 4 个文件、`max_files=3` | `run_check` 0 次、降级「范围过大」、退出码 3 |

- **验收标准**：
  - [ ] 16 个用例全部通过；patch 目标为模块内被调用的真实符号。
  - [ ] `test_no_direct_module_import`、`test_no_rule_duplication` 的职责归主任务 28，本文件不重复实现；如实现，必须只读扫描、不写文件。
  - [ ] 只读快照使用标准库 `hashlib`（测试文件允许）。
- **路径回报**：实际写入 `backend/tests/test_health_service.py`。

## 主任务 21：`backend/tests/test_health_zombie.py`

- **前置**：主任务 8。
- **输入**：`app.health.zombie`、`WalkedFile` 夹具、patch 的 Git 结果。
- **输出**：僵尸三条件测试，共 18 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| HZ-01 | Git 依据候选 | Git 最近提交 >365 天、引用 0 | 候选，`basis="git"`、`idle_days>=365` |
| HZ-02 | mtime 依据候选 | Git off、mtime 分散且 >365 天 | 候选，`basis="mtime"` |
| HZ-03 | 阈值可配置 | `zombie_days=90`、空闲 100 天 | 候选，`idle_days>=90` |
| HZ-04 | 非法阈值回退 | 0、20、4000 | 回退 365 + 中文警告 |
| HZ-05 | 被引用不候选 | 其他文件含其相对路径或 basename | 不输出候选，也不输出无法判定 |
| HZ-06 | Git 不可用 | 非 Git 工作区 | `degraded` 含「Git 历史不可用」；mtime 可信时改用 mtime |
| HZ-07 | Git 单文件超时 | patch `subprocess.run` 抛 `TimeoutExpired` | `GitActivity` 不可用、原因含超时；该文件降级为 mtime/无法判定 |
| HZ-08 | Git 总预算耗尽 | `GitBudget` 剩余 ≤0 | 不再发起命令，整体 Git 依据降级 |
| HZ-09 | mtime 批量检出 | 90% 文件同 1 小时窗口、无 Git | 全部无法判定，原因含「批量检出」 |
| HZ-10 | 引用统计不完整 | 1 个文本文件不可读 | 引用为 0 的候选无法判定，原因含「引用统计不完整」与数量 |
| HZ-11 | 通用名 | `README.md`、`requirements.txt` | 无法判定「入口或配置文件不适用僵尸判定」 |
| HZ-12 | 示例路径豁免 | `lab/uart/uart_demo.c` | 无法判定「示例文件不参与僵尸判定」 |
| HZ-13 | 入口/构建豁免 | `main.py`、`CMakeLists.txt` | 无法判定「入口或配置文件」 |
| HZ-14 | 配置类豁免 | `.env`、`.env.local`、`.gitignore` | 无法判定「配置文件不适用僵尸判定」 |
| HZ-15 | 弱信号不判定 | 仅体积小/扩展名怪/目录名怪 | 不输出候选、不输出无法判定 |
| HZ-16 | 无法判定原因与候选等级 | 混合结果 | 所有 `reason` 非空且中文；候选 `risk_level=建议`、`reference_count=0` |
| HZ-17 | Git 参数安全 | patch `subprocess.run` 捕获参数 | `shell=False`、参数为列表、无写/远程命令、超时 ≤2 秒、环境含三项 GIT 变量 |
| HZ-18 | 三条件缺一 | 缺引用可靠 / 缺时间依据 / 未达阈值 | 分别无法判定或不出候选；仅两条件满足时不出候选 |

- **验收标准**：
  - [ ] 18 个用例全部通过；所有 Git 调用均被 patch，不访问真实网络/远程。
  - [ ] 候选用例同时断言 `reference_count==0` 与 `risk_level==建议`。
  - [ ] 无写文件、无 `git` 写命令。
- **路径回报**：实际写入 `backend/tests/test_health_zombie.py`。

## 主任务 22：`backend/tests/test_health_report.py`

- **前置**：主任务 10。
- **输入**：构造的 `HealthReport`、`render_health_text`、`health_to_json`。
- **输出**：渲染契约测试，共 13 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| HR-01 | text 段落顺序 | 含高风险/建议/僵尸/无法判定/降级/警告 | 总览→高风险→建议→僵尸→无法判定→降级→警告 |
| HR-02 | 各段空状态 | 空结果报告 | 五类空状态文案齐全，警告段省略 |
| HR-03 | 输入错误 text | `status=输入错误` | 只输出输入错误句子，不输出其它段 |
| HR-04 | JSON 中文不转义 | 含中文 message | 原始字符串无 `\uXXXX`，`json.loads` 后中文正确 |
| HR-05 | JSON 顶层键顺序 | 任意报告 | 键顺序与 2.7.1 完全一致 |
| HR-06 | 稳定排序 | 乱序 files/findings/zombies/undetermined/degraded | 符合 2.7.3 排序键 |
| HR-07 | 确定性 | 同一 `now` 运行两次 | 除 `scanned_at`/`duration_ms` 外逐字段一致 |
| HR-08 | 空结果完整 | 空仓库报告 | 全部字段存在、列表 `[]`、统计 0 |
| HR-09 | 无法判定不计问题数 | 2 条无法判定 + 3 条问题 | `undetermined_count=2`，`issue_count=3` |
| HR-10 | 统计不一致降级 | 手工构造不一致 summary | 报告 `部分降级` + 警告 + 可重算字段被修正 |
| HR-11 | 无绝对路径 | 含 `scan_root` 的报告 | 文本与 JSON 无盘符、`C:\`、UNC、用户目录 |
| HR-12 | 降级顺序与去重 | 乱序/重复降级项 | 按 `DEGRADED_ORDER` 再按 reason 排序，重复项去重 |
| HR-13 | 超限/空仓库文案 | 超限报告、空仓库报告 | 分别含「超过上限」「请缩小巡检范围」「仓库内未发现可巡检文件」 |

- **验收标准**：
  - [ ] 13 个用例全部通过；不依赖真实时间，必要时构造固定 `scanned_at`。
  - [ ] 不修改 `common/report.py`，只验证新渲染器。
- **路径回报**：实际写入 `backend/tests/test_health_report.py`。

## 主任务 23：`backend/tests/test_health_cli.py`

- **前置**：主任务 11。
- **输入**：`app.health.cli.main`、临时仓库、`capsys`/`redirect_stdout`。
- **输出**：CLI 测试，共 15 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| HC-01 | 默认参数 | 仅 `--repo` 或省略 | `format=text`、`zombie_days=365`、`git=auto`、`max_files=5000`；`--repo` 缺省按默认规则解析 |
| HC-02 | 退出码 0 | 干净仓库 | 返回 0，stdout 含「未发现问题」类空状态 |
| HC-03 | 退出码 1 | 至少一条高风险 | 返回 1 |
| HC-04 | 退出码 2 | 根不存在/非目录 | 返回 2，中文原因 |
| HC-05 | `--max-files` 边界 | 29、50001、30、50000 | 29/50001 返回 2；30/50000 合法 |
| HC-06 | 退出码 3 | 降级项或文件数超限 | 返回 3 |
| HC-07 | JSON 输出 | `--format json` | stdout 为合法 JSON，字段完整，中文可读 |
| HC-08 | 仓库外写报告 | `--output` 指向仓库外 | 文件存在且为 JSON；stdout 仍有报告 |
| HC-09 | 仓库内写报告拒绝 | `--output` 指向仓库内 | 返回 2，仓库内无新文件 |
| HC-10 | `--output` 为目录 | 指向已存在目录 | 返回 2，中文原因 |
| HC-11 | `--debug` | 默认与 `--debug` 对比 | 默认 stderr 无 `Traceback`/英文异常类名；`--debug` 堆栈只进 stderr |
| HC-12 | 帮助文案 | `--help` | 中文，含全部参数与默认值 |
| HC-13 | `--zombie-days 0` | 非法阈值 | 退出码非 2，输出中文警告，报告记录 365 |
| HC-14 | `--git` 非法值 | `--git bad` | argparse 返回 2 |
| HC-15 | stdout 单报告 | 正常执行 | 只有一份报告，末尾单换行，无调试信息污染 |

- **验收标准**：
  - [ ] 15 个用例全部通过；不启动 uvicorn、不监听端口。
  - [ ] 断言 stdout/stderr 分离，默认模式无英文堆栈。
- **路径回报**：实际写入 `backend/tests/test_health_cli.py`。

## 主任务 24：`backend/tests/test_readme_scan.py`

- **前置**：主任务 6。
- **输入**：`app.readme.scanner`、临时 Markdown/Demo 目录。
- **输出**：标题提取与 Demo 识别测试，共 20 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| RS-01 | ATX 一级标题 | `# 串口通信实验` | 标题「串口通信实验」，`title_source=atx` |
| RS-02 | 无标题回退 | 正文无 ATX | 文件名词干，`fallback_filename` |
| RS-03 | YAML front matter | 头部 `---` 块内含 `# x`，正文有 H1 | 跳过头部，取正文 H1 |
| RS-04 | 未闭合 front matter | 只有起始 `---` | 按普通内容处理 + 中文警告 |
| RS-05 | 围栏代码块 | ``` 与 ~~~ 内含 `# 注释` | 不识别为标题；正文 H1 生效 |
| RS-06 | HTML 注释 | `<!-- # 标题 -->` | 注释内不识别 |
| RS-07 | H1 优先级 | 先 H2 后 H1 | 取 H1 而非首个标题 |
| RS-08 | 无空格井号 | `#标题` | 不识别，回退文件名 |
| RS-09 | 行内代码 | `# 使用 \`uart\` 实验` | 标题文本去除反引号，文字保留 |
| RS-10 | 标题截断 | 201 字符 H1 | 截断到 200，`truncated=True` |
| RS-11 | 编码回退 | GB18030 编码的 `.md` | 标题正确解码，不报错 |
| RS-12 | 空文档 | 0 字节、纯空白 | 回退文件名，继续扫描 |
| RS-13 | 强证据入口 | `main.py` | Demo `confirmed`，证据含 `main.py` |
| RS-14 | 强证据构建 | `CMakeLists.txt`、`requirements.txt` | Demo `confirmed` |
| RS-15 | 弱证据名称 | `lab/uart/uart_demo.c` 单源码无 README | `suspected`，证据含名称提示词 |
| RS-16 | 弱证据组合 | 2 个源码 + `README.md` | `suspected`，证据含「源码文件 N 个」与 README |
| RS-17 | 无法判定 | 1 个源码、无 README/入口/构建/提示 | `undetermined`，中文原因，不计入 Demo 数 |
| RS-18 | 排除目录 | `tests`、`test`、`assets`、`docs`、`notes` | 均不进入 Demo 分区 |
| RS-19 | 测试文件不算源码 | `test_demo.py`、`demo_test.py`、`x.test.js`、`x.spec.js` | 不计入源码文件数 |
| RS-20 | 根目录不候选 | 根目录含 `main.py` | 根目录不识别为 Demo，`demo_project_count=0` |

- **验收标准**：
  - [ ] 20 个用例全部通过；不写临时目录之外的文件。
  - [ ] 所有 Demo 结论断言 `confidence` 与证据，不断言「已确认」以外的主观结论。
- **路径回报**：实际写入 `backend/tests/test_readme_scan.py`。

## 主任务 25：`backend/tests/test_readme_index.py`

- **前置**：主任务 13。
- **输入**：`app.readme.index`、`DocEntry`/`DemoProject` 夹具。
- **输出**：索引结构与渲染测试，共 14 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| RI-01 | 相对路径 | `docs/x.md` | 输出 `[x](docs/x.md)`，无绝对路径、无 `\` |
| RI-02 | 空格路径 | `docs/lab 03.md` | 输出 `(<docs/lab 03.md>)` |
| RI-03 | 中文路径 | `docs/lab03_串口通信实验.md` | 原样中文，无 `%E4` |
| RI-04 | 锚点规则 | 现有标题映射含重名 | 仅现有标题生成锚点；无标题 `anchor=None`；重名 `-1/-2` |
| RI-05 | 排序 | 目录/文档混合 | 目录项先于文档项，各按 `path` 升序 |
| RI-06 | 去重 | 同一 `path` 出现两次 | 只保留一次 + 中文警告 |
| RI-07 | 同标题不合并 | 两个不同路径同标题 | 两条，链接文本含路径末段可区分 |
| RI-08 | Demo 排序 | confirmed/suspected 混合 | confirmed 在前，各自 `path` 升序 |
| RI-09 | 空目录省略 | 空目录 | 不生成目录项 |
| RI-10 | 空分区占位 | 无文档或无 Demo | 分区标题 + `（无）` |
| RI-11 | 根 README | 根 `README.md` | 标题「根 README」，`link="README.md"` |
| RI-12 | 标记可选 | `with_markers=False/True` | 默认无标记；True 输出 TOC 标记 |
| RI-13 | 层级深度 | `a/b/c.md` | `depth` 与目录层级正确 |
| RI-14 | Demo 目录链接 | `lab/uart` | 链接以 `/` 结尾 |

- **验收标准**：
  - [ ] 14 个用例全部通过；`render_index_markdown()` 输出可被 Markdown 解析。
  - [ ] 断言索引条目数等于文档数 + Demo 数（不含目录项）或按实现口径明确。
- **路径回报**：实际写入 `backend/tests/test_readme_index.py`。

## 主任务 26：`backend/tests/test_readme_compare.py`

- **前置**：主任务 14。
- **输入**：`app.readme.compare`、README 文本夹具、`TocIndex` 夹具。
- **输出**：区块识别、差异与替换片段测试，共 16 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| RC-01 | TOC 标记范围 | `<!-- TOC -->`…`<!-- /TOC -->`，大小写/空白变化 | 行范围精确，`marker_kind="TOC"` |
| RC-02 | BEGIN/END 标记 | `<!-- BEGIN TOC -->`…`<!-- END TOC -->` | 识别，`marker_kind="BEGIN_TOC"` |
| RC-03 | 标题区块 | `## 目录` 后接条目，再到下一个 `##` | 从标题行到下一个同级/更高级标题前 |
| RC-04 | 区块缺失 | README 无标记无目录标题 | `toc_block_found=False` + 无法判定 + 完整片段 + 插入提示 |
| RC-05 | 新增差异 | 新索引有、旧区块无 | 一条「新增」，`old_*` 为 null |
| RC-06 | 删除差异 | 旧区块有、新索引无 | 一条「删除」，`new_*` 为 null |
| RC-07 | 移动差异 | 同 path、层级/父目录变化 | 一条「移动」 |
| RC-08 | 标题变化 | 同 path、标题文本变化 | 一条「标题变化」 |
| RC-09 | 移动+改名 | 同 path 同时层级与标题变化 | 两条，不合并 |
| RC-10 | 差异排序 | 四类乱序输入 | 新增→删除→移动→标题变化，再按 `path` |
| RC-11 | 替换片段一致 | 任意索引与区块 | 正文与 `render_index_markdown()` 逐字一致；标记/标题行沿用 |
| RC-12 | README 不修改 | 读取前后 | `sha256` 与 `mtime` 完全一致 |
| RC-13 | 外链忽略 | `http/https/mailto/#anchor` | 不参与差异 |
| RC-14 | README 缺失 | `locate_readme()` 返回 None | 报告 `readme_found=False` + 无法判定 + 完整片段 |
| RC-15 | README 越界 | `--readme ../x.md` | `validate_readme_path()` 返回中文错误 |
| RC-16 | README 大小写 | 仅 `readme.md` 或仅 `README.md` | 两种情况均可定位 |

- **验收标准**：
  - [ ] 16 个用例全部通过；不写 README，不使用 `write_text`/`write_bytes`。
  - [ ] 差异字段完整，排序稳定。
- **路径回报**：实际写入 `backend/tests/test_readme_compare.py`。

## 主任务 27：`backend/tests/test_readme_cli.py`

- **前置**：主任务 17。
- **输入**：`app.readme.cli.main`、临时仓库与 README、`capsys`。
- **输出**：README CLI 测试，共 15 个用例。
- **用例清单**：

| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| RCLI-01 | 退出码 0 | 无差异、无无法判定 | 返回 0 |
| RCLI-02 | 退出码 1 | 至少一条差异 | 返回 1 |
| RCLI-03 | 退出码 2 | 根不存在/非目录 | 返回 2，中文原因 |
| RCLI-04 | 退出码 2 | `--readme` 越界/不可读 | 返回 2 |
| RCLI-05 | 退出码 3 | 目录区块缺失/无法判定 | 返回 3 |
| RCLI-06 | 默认自动对比 | 根目录有 `README.md` | 自动定位并输出差异/片段 |
| RCLI-07 | 仓库外写 JSON | `--output` 仓库外 | 文件存在且为 JSON |
| RCLI-08 | 仓库内写拒绝 | `--output` 仓库内 | 返回 2，无新文件 |
| RCLI-09 | 覆盖 README 拒绝 | `--output` 等于 README | 返回 2，README 哈希/mtime 不变 |
| RCLI-10 | 帮助文案 | `--help` | 中文，含全部参数与默认值 |
| RCLI-11 | 调试模式 | 默认与 `--debug` | 默认无英文堆栈；`--debug` 堆栈只进 stderr |
| RCLI-12 | stdout 单报告 | 正常执行 | 只有一份报告，无调试污染 |
| RCLI-13 | JSON 字段 | `--format json` | 字段完整、中文不转义、可解析 |
| RCLI-14 | `--max-files` 边界 | 29、50001 | 返回 2；合法值不报错 |
| RCLI-15 | 无网络 | patch `socket.socket` | 正常完成，不触发 socket |

- **验收标准**：
  - [ ] 15 个用例全部通过；不写 README、不启动服务。
  - [ ] 退出码优先级 `2 > 3 > 1 > 0` 逐项断言。
- **路径回报**：实际写入 `backend/tests/test_readme_cli.py`。

---

## 6. 兼容性、回归与交付门禁

## 主任务 28：导入兼容逐文件核查

- **交付物**：核查记录（仓库外或终端留存）。
- **前置**：主任务 4、11、12、17、18。
- **输入**：17 个新增产品文件；`backend/tests/test_engine.py::test_import_direction` 的 18 项白名单。
- **输出**：逐文件导入清单与 AST 核查结论。
- **逐文件导入清单（与 design 2.10.2 一致）**：

| 文件 | 允许的 `from ... import` | 必须用 `import X` 的模块 |
|------|--------------------------|---------------------------|
| `backend/app/shared/repo_walk.py` | `__future__`、`dataclasses`、`pathlib`、`typing`、`..core.rules.common.file_io` | `os` |
| `backend/app/shared/text_io.py` | `__future__`、`pathlib`、`typing`、`..core.rules.common.file_io` | 无 |
| `backend/app/shared/__init__.py` | `.repo_walk`、`.text_io` | 无 |
| `backend/app/health/models.py` | `__future__`、`dataclasses`、`enum`、`typing`、`..core.rules.common.models` | `datetime` |
| `backend/app/health/service.py` | `__future__`、`pathlib`、`typing`、`time`、`..core.rules.common.config`、`..core.rules.common.models`、`..core.rules.engine`、`..readme.models`、`..readme.scanner`、`..shared.repo_walk`、`..shared.text_io`、`.models`、`.zombie` | `datetime` |
| `backend/app/health/zombie.py` | `__future__`、`dataclasses`、`pathlib`、`time`、`typing`、`..core.rules.common.config`、`..shared.repo_walk`、`..shared.text_io`、`.models` | `datetime`、`os`、`re`、`subprocess` |
| `backend/app/health/render.py` | `__future__`、`typing`、`.models` | `json` |
| `backend/app/health/cli.py` | `__future__`、`argparse`、`pathlib`、`typing`、`..core.rules.common.config`、`..shared.repo_walk`、`.models`、`.render`、`.service` | `sys`、`traceback` |
| `backend/app/health/__init__.py` | `.models`、`.service` | 无 |
| `backend/app/readme/models.py` | `__future__`、`dataclasses`、`enum`、`typing` | 无 |
| `backend/app/readme/scanner.py` | `__future__`、`pathlib`、`typing`、`..shared.repo_walk`、`..shared.text_io`、`.models` | `fnmatch`、`re` |
| `backend/app/readme/index.py` | `__future__`、`typing`、`.models` | `re` |
| `backend/app/readme/compare.py` | `__future__`、`pathlib`、`typing`、`..shared.repo_walk`、`..shared.text_io`、`.models` | `re` |
| `backend/app/readme/service.py` | `__future__`、`pathlib`、`time`、`typing`、`..shared.repo_walk`、`..shared.text_io`、`.compare`、`.index`、`.models`、`.render`、`.scanner` | `datetime` |
| `backend/app/readme/render.py` | `__future__`、`typing`、`.models` | `json` |
| `backend/app/readme/cli.py` | `__future__`、`argparse`、`pathlib`、`typing`、`..shared.repo_walk`、`.compare`、`.models`、`.render`、`.service` | `sys`、`traceback` |
| `backend/app/readme/__init__.py` | `.models`、`.service` | 无 |

- **子任务与验收**：
  - [ ] 对 17 个文件逐个用 AST 检查 `ast.ImportFrom` 的根模块，非相对导入必须落在 18 项白名单：`__future__、argparse、ast、collections、dataclasses、enum、ipaddress、json、math、os、pathlib、re、sys、time、traceback、types、typing、unittest`。
  - [ ] `datetime`、`subprocess`、`fnmatch`、`hashlib`、`urllib.parse`、`stat` 等白名单外模块全部使用 `import X` 形式；产品代码不使用 `hashlib`。
  - [ ] 新增包访问阶段 1 一律相对导入（如 `from ..core.rules.engine import run_check`），不得出现 `from app...`/`import app...`。
  - [ ] `shared/**` 不导入 `health`/`readme`；`readme/**` 不导入 `health`；`health/**` 仅可导入 `readme.models`/`readme.scanner`。
  - [ ] 新包中 `naming`、`code_scan`、`link_check`、`sensitive` 的导入命中 0 次。
  - [ ] 新包中 `fastapi`、`uvicorn`、`starlette`、`pydantic`、`socket`、`http.client`、`urllib.request`、`requests`、`aiohttp` 命中 0 次。
  - [ ] 不修改 `backend/tests/test_engine.py`；运行 `test_import_direction` 通过。
  - [ ] 核查记录注明「检查文件数 17、失败 0」。
- **停止条件**：任一文件导入不合规，停止并修复后重跑本任务。
- **路径回报**：回报核查记录路径与 17 个文件清单。

## 主任务 29：回归与冻结哈希门禁

- **交付物**：回归记录（仓库外或终端留存）。
- **前置**：主任务 27、28。
- **输入**：主任务 1 的基线记录、全部新增文件。
- **输出**：逐项回归数值与哈希差异。
- **子任务与验收（必须按顺序）**：
  - [ ] 29.1 只跑原有测试模块：`python -m unittest tests.test_engine tests.test_naming tests.test_code_scan tests.test_link_check tests.test_sensitive tests.test_manifest tests.test_api -v` → 原有 164 passed + 1 skipped，0 failed / 0 error。
  - [ ] 29.2 CLI 回归：`python -m unittest tests.test_cli -v` → 12 passed，参数/退出码/stdout/stderr 与阶段 1 一致。
  - [ ] 29.3 新增 9 个测试文件全部运行：`python -m unittest tests.test_repo_walk tests.test_health_service tests.test_health_zombie tests.test_health_report tests.test_health_cli tests.test_readme_scan tests.test_readme_index tests.test_readme_compare tests.test_readme_cli -v` → 0 failed / 0 error，用例数与任务 19～27 的清单一致。
  - [ ] 29.4 全量发现：`python -m unittest discover -s tests -v` → 0 failed / 0 error；原有无符号链接的 7 个测试模块必须保持 164 passed + 1 skipped；新增用例中若因平台无法创建符号链接而 skip，必须写明中文原因并计入交付报告，不得出现 failed/error。
  - [ ] 29.5 13 个冻结文件 SHA-256 与主任务 1 基线逐行比对，差异文件数 == 0。
  - [ ] 29.6 `backend/requirements.txt` SHA-256 不变；`test_requirements_txt` 通过；三段式结构未变。
  - [ ] 29.7 `backend/app/api/**` 与 `backend/app/static/index.html` 文件清单/哈希不变；`test_api` 全通过。
  - [ ] 29.8 `test_import_direction` 通过且方法体未修改；`test_engine.py` 文件哈希与基线一致。
- **停止条件**：任一回归失败或哈希差异非 0，停止，不得进入主任务 30。
- **路径回报**：回报回归记录路径、`Ran` 数值、哈希差异数。

## 主任务 30：只读实测与零网络/零端口静态检查

- **交付物**：实测记录（仓库外或终端留存）。
- **前置**：主任务 29。
- **输入**：`demo-repo/`、两条新增 CLI、新增包源码。
- **输出**：只读快照差异、静态命中数、性能抽样。
- **子任务与验收**：
  - [ ] 30.1 对 `demo-repo/` 执行 `python -m app.health.cli --repo ../demo-repo --format text` 与 `--format json`，记录 text 与 JSON 实际输出（作为验收演示，不写入被巡检仓库）。
  - [ ] 30.2 对 `demo-repo/` 执行 `python -m app.readme.cli --repo ../demo-repo --format text` 与 `--format json`，记录输出；确认「README 未找到/区块缺失 → 无法判定 + 完整片段 + 需人工插入」。
  - [ ] 30.3 扫描前后比对 `demo-repo` 文件列表与每个文件 `size + sha256 + mtime`，差异必须为 0；不得新增 `__pycache__`、报告、缓存、日志。
  - [ ] 30.4 对比 README（若存在）的 SHA-256 与 mtime，差异为 0；确认无 `--write`/`--apply` 参数。
  - [ ] 30.5 静态扫描新包：`fastapi|uvicorn|starlette|pydantic|socket|http.client|urllib.request|requests|aiohttp` 命中 0；`uvicorn`、`http.server`、端口绑定调用命中 0。
  - [ ] 30.6 静态扫描新包：四个检查模块导入命中 0；`from app...`/`import app...` 命中 0；写操作仅允许出现在 `health/cli.py`、`readme/cli.py` 的 `--output` 分支，且必须校验真实目标路径位于被巡检仓库根之外、不得等于 README；被巡检根内写操作命中数必须为 0。
  - [ ] 30.7 性能抽样：`demo-repo` 两条 CLI 端到端耗时记录；5000 文件场景若可构造，健康巡检 ≤60 秒、README ≤20 秒；超预算仅警告不中断。
  - [ ] 30.8 Git 只读验证：确认命令为 `git ... log -1 --format=%ct`，无写命令/远程命令；git 不可用时降级正常。
  - [ ] 30.9 零网络实测：用 `patch("socket.socket", side_effect=AssertionError)` 包裹两条 CLI 的进程内调用，正常完成。
- **停止条件**：任一差异非 0 或静态命中非 0，停止并修复。
- **路径回报**：回报实测记录路径与差异数。

## 主任务 31：中文使用文档 `docs/repo_health_readme_usage.md`

- **交付物**：`docs/repo_health_readme_usage.md`。
- **前置**：主任务 17、29。
- **并行组**：D（可与主任务 30 并行，但必须在 32 之前完成）。
- **输入**：spec 8、design 2.9、主任务 30 的实际 text/JSON 输出。
- **输出**：中文使用说明。
- **章节与内容要求**：
  - [ ] 31.1 适用范围与运行前提：Python 3.10+、工作目录 `backend/`、零第三方依赖、只读离线。
  - [ ] 31.2 两套 CLI 完整命令模板与示例：健康巡检、README 目录生成；含 `--repo`、`--format`、`--output`、`--zombie-days`、`--git`、`--max-files`、`--config`、`--readme`、`--debug`。
  - [ ] 31.3 参数表：逐个解释默认值、取值范围、非法值行为；`--output` 必须在仓库外，README CLI 还不得指向 README。
  - [ ] 31.4 退出码表：`0/1/2/3` 与优先级 `2 > 3 > 1 > 0`；分别说明健康巡检与 README 的触发条件差异（无法判定在 README 侧为 3，在健康侧不单独触发 3）。
  - [ ] 31.5 text 与 JSON 示例：使用 `demo-repo` 实际输出；标注「示例，实际内容以巡检结果为准」；JSON 说明 `ensure_ascii=False`、`indent=2`、字段稳定。
  - [ ] 31.6 僵尸口径：三条件、Git/mtime 依据、批量检出 80%/1 小时、引用统计不完整、通用名/入口/示例/配置豁免、`zombie_days` 默认 365（30～3650）。
  - [ ] 31.7 无法判定口径：无法判定不是问题、不计入高风险/建议、必须带中文原因；与降级项的区别。
  - [ ] 31.8 README 只读与人工替换流程：审阅差异 → 复制替换片段 → 在工具外手工粘贴 → 自检链接；明确无 `--write/--apply`、工具不写 README。
  - [ ] 31.9 故障排查：Git 不可用、非 Git 工作区、编码失败、文件数超限、深度超限、权限失败、符号链接逃逸、目录区块缺失、`--output` 越界、README 未找到。
  - [ ] 31.10 只读/离线/零端口/零依赖声明与边界：5 MB、5000 文件、64 层、Git 2 秒/30 秒、风险等级仅两级。
- **验收标准**：
  - [ ] 全中文；命令可复制执行；示例不泄露绝对路径、真实凭据。
  - [ ] 不出现「自动写入 README」「一键修改」等误导性描述。
  - [ ] 文档路径精确为 `docs/repo_health_readme_usage.md`。
- **路径回报**：实际写入 `docs/repo_health_readme_usage.md`。

## 主任务 32：交付清单与最终验收

- **交付物**：最终交付清单（回复文本 + 仓库外记录）。
- **前置**：主任务 30、31。
- **输入**：主任务 1～31 的全部记录。
- **输出**：可核对的交付结论。
- **子任务与验收**：
  - [ ] 32.1 列出 27 个新增文件的实际路径：17 个产品文件 + 9 个测试文件 + 1 个文档；逐项确认存在且非空。
  - [ ] 32.2 确认 0 个既有文件被修改；13 个冻结文件 SHA-256 差异 0；`api/**`、`static/index.html`、`requirements.txt`、`test_engine.py`、`test_cli.py` 未改动。
  - [ ] 32.3 确认原有 164 passed + 1 skipped；CLI 12 passed；新增 9 个测试文件全通过；全量 discover 全通过。
  - [ ] 32.4 确认只读实测差异 0；README 哈希与 mtime 不变；零网络、零端口、零 Web 依赖、零第三方依赖。
  - [ ] 32.5 确认导入兼容：17 个文件白名单合规、相对导入合规、四模块导入 0、Web/网络导入 0。
  - [ ] 32.6 展示 `demo-repo` 的 text 与 JSON 实际输出摘要（健康巡检 + README），并说明「README 未找到/区块缺失 → 无法判定 + 完整片段 + 需人工插入」。
  - [ ] 32.7 输出最终交付清单并**停止**：不进入任何产品代码实现、不修改任何文件、不开始下一阶段。
- **停止条件**：任一验收项未满足，停止并输出未通过项，不得宣称交付完成。
- **路径回报**：回报交付清单与全部实际文件路径。

---

## 7. 执行顺序与验收门禁总表

| 门禁 | 触发时机 | 必须满足 | 失败动作 |
|------|---------|---------|---------|
| G0 | 主任务 1 后 | 基线 164+1、CLI 12、13 文件 SHA 已记录 | 停止 |
| G1 | 主任务 2～4 后 | shared 可导入、无反向依赖、遍历测试可运行 | 停止 |
| G2 | 主任务 5、6 后 | 标题提取与 Demo 分层符合 7.1/7.2 | 停止 |
| G3 | 主任务 7～11 后 | 健康报告可生成、`run_check` 1 次、CLI 退出码正确 | 停止 |
| G4 | 主任务 13～18 后 | README 索引/差异/片段/CLI 可运行、不写 README | 停止 |
| G5 | 主任务 19～27 后 | 9 个测试文件全通过、0 failed / 0 error | 停止 |
| G6 | 主任务 28 后 | 17 文件导入合规、四模块/Web/网络导入 0 | 停止 |
| G7 | 主任务 29 后 | 164+1、CLI 12、全量通过、13 SHA 差异 0 | 停止 |
| G8 | 主任务 30 后 | 只读差异 0、零网络/零端口/零依赖命中 0 | 停止 |
| G9 | 主任务 31、32 后 | 文档完成、交付清单完整 | 停止 |

**最终交付物清单（27 个新增文件）**：

1. `backend/app/shared/__init__.py`
2. `backend/app/shared/repo_walk.py`
3. `backend/app/shared/text_io.py`
4. `backend/app/health/__init__.py`
5. `backend/app/health/models.py`
6. `backend/app/health/service.py`
7. `backend/app/health/zombie.py`
8. `backend/app/health/render.py`
9. `backend/app/health/cli.py`
10. `backend/app/readme/__init__.py`
11. `backend/app/readme/models.py`
12. `backend/app/readme/scanner.py`
13. `backend/app/readme/index.py`
14. `backend/app/readme/compare.py`
15. `backend/app/readme/service.py`
16. `backend/app/readme/render.py`
17. `backend/app/readme/cli.py`
18. `backend/tests/test_repo_walk.py`
19. `backend/tests/test_health_service.py`
20. `backend/tests/test_health_zombie.py`
21. `backend/tests/test_health_report.py`
22. `backend/tests/test_health_cli.py`
23. `backend/tests/test_readme_scan.py`
24. `backend/tests/test_readme_index.py`
25. `backend/tests/test_readme_compare.py`
26. `backend/tests/test_readme_cli.py`
27. `docs/repo_health_readme_usage.md`

> 本文档到此结束；执行阶段严格按主任务编号推进，每个任务完成后回报实际路径，任一失败停止。
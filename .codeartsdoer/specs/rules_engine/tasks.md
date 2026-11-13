# RepoGuard 规则引擎（rules_engine）实施任务清单

> 依据：`.codeartsdoer/specs/rules_engine/spec.md`（666 行，唯一需求来源）与 `.codeartsdoer/specs/rules_engine/design.md`（2196 行，技术设计）。
> 权威口径：文件路径与公开签名以 design.md **2.4.3** 为准；文件间导入方向以 **2.4.4** 为准；需求覆盖以 **2.11** 为准。
> 本文档只做任务规划，不含任何实现代码；签名块仅表达契约（以 `...` 省略实现体）。

## 任务拓扑与并行组

**关键路径（串行、不可压缩）**

`T01 工程骨架 → T02 数据模型 → T03 规则配置 / T05 只读 IO → T06～T09 四检查模块 → T11 汇总入口 → T12 CLI → T21 CLI 测试 → T22 端到端验收 → T24 使用文档 → T25 最终回归`

**可并行任务组**

| 并行组 | 触发条件 | 可并行任务 | 说明 |
|--------|---------|-----------|------|
| A | T01 完成后 | T14 样例清单与样例仓库、T23 requirements.txt | 与 T02 无数据依赖，可提前产出 |
| B | T02 完成后 | T03 规则配置、T04 清单解析、T10 报告渲染 | 三者只依赖 `common/models.py`，互不引用 |
| C | T05 完成后 | T06 命名、T07 代码、T08 链接、T09 敏感 | 四模块**零横向依赖**，按 design 2.4.4 只依赖 `common` |
| D | T06～T09 完成后 | T15、T16、T17、T18、T19 五个单元测试文件 | 每个测试文件只测对应模块 |
| E | T20 完成后 | T22 端到端验收 | 端到端依赖集成测试先通过 |

**任务编号总表（25 个主任务）**

| 编号 | 主任务 | 依赖 |
|------|--------|------|
| T01 | 工程骨架与运行环境 | 无 |
| T02 | 数据模型与报告结构 | T01 |
| T03 | 规则配置中心 | T02 |
| T04 | 变更清单解析 | T02 |
| T05 | 只读文件访问与安全沙箱 | T02、T03 |
| T06 | 命名与目录归属检查 | T03、T05 |
| T07 | 代码注释与高危写法检查 | T03、T05 |
| T08 | Markdown 链接格式检查 | T03、T05 |
| T09 | 敏感信息与大文件检查 | T03、T05 |
| T10 | 中文摘要与 JSON 序列化 | T02 |
| T11 | 汇总入口与模块调度 | T03、T04、T05、T06、T07、T08、T09、T10 |
| T12 | 命令行入口与退出码 | T11 |
| T13 | 公共门面 `rules/__init__.py` | T02、T03、T10、T11 |
| T14 | 样例变更清单与样例仓库 | T01 |
| T15 | `test_manifest.py` 单元测试 | T04 |
| T16 | `test_naming.py` 单元测试 | T06 |
| T17 | `test_code_scan.py` 单元测试 | T07 |
| T18 | `test_link_check.py` 单元测试 | T08 |
| T19 | `test_sensitive.py` 单元测试 | T09 |
| T20 | `test_engine.py` 集成测试 | T11、T13、T15、T16、T17、T18、T19 |
| T21 | `test_cli.py` 命令行测试 | T12、T20 |
| T22 | 端到端验收（样例清单 → engine → 分组报告 + 退出码） | T14、T21 |
| T23 | 依赖清单 `backend/requirements.txt` | T01 |
| T24 | 中文使用说明 `docs/rules_engine_usage.md` | T22 |
| T25 | 全量回归与交付验收 | T22、T23、T24 |

**全局约束（对全部任务生效）**

- 所有产品 Python 源码只允许放在 `backend/app/` 下；四个检查模块与汇总入口固定在 `backend/app/core/rules/` 顶层。
- 运行工作目录固定为 `backend/`，包名为 `app.core.rules`；测试统一使用标准库 `unittest`，禁止新增第三方依赖。
- 所有文件 UTF-8 无 BOM 保存；输出统一 `\n`、路径统一 `/`。
- 只读、离线、不执行被扫描代码；不向仓库写入任何检查结果。
- `rule_id` 一经分配不得改名（spec 4.4 第 1 条）。
- 任何任务都不得修改 `frontend/`、`backend/app/api/`、`backend/app/db/`、`backend/app/models/`、`backend/app/services/`。

---

## 1. 工程骨架与运行环境

**依赖**：无
**目标**：建立可导入的包结构，验证解释器可用，避免后续所有任务因环境问题返工。

### 1.1 创建包标记文件

- [ ] 完成 1.1 创建包标记文件

- **创建文件（完整相对路径）**：
  - `backend/app/__init__.py`
  - `backend/app/core/__init__.py`
  - `backend/app/core/rules/common/__init__.py`
- **内容契约**：三个文件均为包标记，`__all__: tuple[str, ...] = ()`，不承载任何逻辑；文件首行 `from __future__ import annotations`。
- **验收标准**：
  - 三个文件存在且非空（空目录不被版本库跟踪）。
  - 三个文件不含函数、类、常量、导入语句（只允许 `__all__`）。
  - 在 `backend/` 目录下执行 `python -c "import app"`、`python -c "import app.core"` 不报错。
  - 不创建 `backend/__init__.py`（design 2.4.2 明确不推荐从仓库根以 `backend.` 前缀运行）。

### 1.2 验证解释器与运行工作目录

- [ ] 完成 1.2 验证解释器与运行工作目录

- **涉及路径**：`backend/`（工作目录，不新增文件）
- **验收标准**：
  - `python --version` 输出版本号且 ≥ 3.10。
  - `python -c "import ast, dataclasses, enum, argparse, json, pathlib, ipaddress, unicodedata, unittest"` 退出码为 0。
  - 在 `backend/` 下执行 `python -c "import app.core.rules"`，此时允许因 `rules/__init__.py` 尚未创建而报 `ModuleNotFoundError`；记录该状态并在 T13 完成后复验通过。
  - 若解释器不可用，在本任务内记录阻塞项并切换/修复解释器，不得进入 T02。

---

## 2. 数据模型与报告结构

**依赖**：T01
**目标**：落地 spec 第 6 章全部数据结构与不变量，成为四模块与汇总入口的唯一类型契约。

### 2.1 枚举定义

- [ ] 完成 2.1 枚举定义

- **创建文件（完整相对路径）**：`backend/app/core/rules/common/models.py`
- **函数/类型签名**：
```python
class ChangeStatus(Enum): ...
class IssueLevel(Enum): ...
class ReportStatus(Enum): ...
class ExitCode(IntEnum): ...
```
- **验收标准**：
  - `ChangeStatus` 取值仅 `A`/`M`/`D`；构造时接受小写并归一化为大写，其他值拒绝。
  - `IssueLevel` 取值仅"必须修改"/"优化建议"，禁止英文别名（spec 6.2 第 1 条）。
  - `ReportStatus` 取值仅"正常"/"部分降级"/"输入错误"（spec 6.3 第 5 条）。
  - `ExitCode` 取值为 `OK=0`、`MUST_FIX=1`、`INPUT_ERROR=2`、`EXECUTION_ERROR=3`，且为 `IntEnum` 以便直接作为进程退出码。
  - 模块只导入标准库，不导入任何 `app.core.rules` 内其他文件（design 2.4.4 叶子节点约束）。

### 2.2 冻结数据结构与字段约束

- [ ] 完成 2.2 冻结数据结构与字段约束

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/models.py`（在 2.1 基础上追加）
- **函数/类型签名**：
```python
class ChangeEntry: ...
class UnparsedLine: ...
class Finding: ...
class FileGroup: ...
class CheckSummary: ...
class DegradedModule: ...
class CheckReport: ...
class ManifestParseResult: ...
class ModuleResult: ...
```
- **字段契约（必须逐条实现）**：
  - `ChangeEntry(status, path, line_no, raw=None, duplicate_count=1)`
  - `UnparsedLine(line_no, raw, reason)`
  - `Finding(level, file_path, message, suggestion, rule_id, line_no=None, excerpt=None)`
  - `FileGroup(file_path, status, findings=(), skip_reason=None, duplicate_count=1)`
  - `CheckSummary(entry_count, issue_count, must_fix_count, suggestion_count, skipped_file_count, degraded_module_count, unparsed_line_count)`
  - `DegradedModule(module, reason)`
  - `CheckReport(status, summary, files=(), unparsed_lines=(), degraded_modules=(), warnings=())`
  - `ManifestParseResult(entries=(), unparsed_lines=())`
  - `ModuleResult(findings=(), skip_reason=None)`
- **验收标准**：
  - 全部为 `@dataclass(frozen=True, slots=True)`；集合字段使用 `tuple`，不允许 `list`。
  - `ChangeEntry` 构造期校验：`path` 非空、以 `/` 分隔、不以 `/` 或盘符开头、`line_no ≥ 1`、`duplicate_count ≥ 1`、`raw` 超 500 字符截断。
  - `Finding` 构造期校验：`message` 8～200 字符、`suggestion` ≤ 300 字符、`excerpt` ≤ 60 字符且超长截断；`line_no` 为 `None` 或 ≥ 1。
  - 报告对象可无损转 JSON：字段中不出现 `Path`、`datetime`、异常对象。
  - 9 个类不导出私有 `_` 前缀符号。

### 2.3 构造、合并、统计与不变量校验

- [ ] 完成 2.3 构造、合并、统计与不变量校验

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/models.py`
- **函数签名**：
```python
def make_finding(
    *,
    level: IssueLevel,
    file_path: str,
    message: str,
    suggestion: str,
    rule_id: str,
    line_no: int | None = None,
    excerpt: str | None = None,
) -> Finding: ...

def merge_findings(
    findings: Sequence[Finding],
    *,
    max_per_rule_per_file: int = 5,
    module_label: str = "",
) -> tuple[Finding, ...]: ...

def empty_summary(
    *,
    entry_count: int = 0,
    skipped_file_count: int = 0,
    degraded_module_count: int = 0,
    unparsed_line_count: int = 0,
) -> CheckSummary: ...

def build_report(
    *,
    status: ReportStatus,
    files: Sequence[FileGroup],
    unparsed_lines: Sequence[UnparsedLine] = (),
    degraded_modules: Sequence[DegradedModule] = (),
    warnings: Sequence[str] = (),
) -> CheckReport: ...

def validate_report(report: CheckReport) -> tuple[str, ...]: ...
```
- **验收标准**：
  - `make_finding` 是四必填字段 + `rule_id` 的唯一构造入口，其余模块不得直接 `Finding(...)` 构造。
  - `merge_findings` 按 `rule_id` 聚合，超过 `max_per_rule_per_file` 时保留前 N 条并追加 1 条"另有 N 处同类问题"（`module_label` 用于中文描述），输出顺序稳定。
  - `empty_summary` 生成全零统计，`issue_count/must_fix_count/suggestion_count` 均按 0 计算。
  - `build_report` 由 `files` 反推 `issue_count`、`must_fix_count`、`suggestion_count`、`skipped_file_count`、`entry_count`，保证 spec 6.3 与 design 2.3.2（4）的 5 条不变量成立。
  - `validate_report` 返回中文错误说明列表，空元组表示通过；不抛异常。
  - 无问题时 `build_report` 返回结构完整、统计全零、列表为空元组的报告（spec 5.6.1 第 9 条）。

---

## 3. 规则配置中心

**依赖**：T02
**目标**：把全部阈值、目录映射、高危/可疑/敏感特征集中到 `common/config.py`，满足 spec 4.4 第 2 条"改阈值不改判定逻辑"。

### 3.1 配置数据结构与默认值

- [ ] 完成 3.1 配置数据结构与默认值

- **创建文件（完整相对路径）**：`backend/app/core/rules/common/config.py`
- **函数/类型签名**：
```python
@dataclass(frozen=True, slots=True)
class RuleConfig: ...

@dataclass(frozen=True, slots=True)
class PatternSpec:
    rule_id: str
    pattern: Pattern[str]
    level: IssueLevel
    message: str
    suggestion: str
    language: str = "any"
    exemptable: bool = True

@dataclass(frozen=True, slots=True)
class ConfigBuildResult:
    config: RuleConfig
    warnings: tuple[str, ...] = ()

DEFAULT_CONFIG: RuleConfig

def default_config() -> RuleConfig: ...
```
- **`RuleConfig` 字段与默认值（15 项，必须齐全）**：
  1. `large_file_warn_mb: float = 1.0`
  2. `large_file_fail_mb: float = 5.0`
  3. `code_scan_max_mb: float = 5.0`
  4. `large_text_scan_timeout_s: float = 1.0`
  5. `per_file_budget_ms: int = 300`
  6. `link_max_per_file: int = 200`
  7. `max_findings_per_rule_per_file: int = 5`
  8. `directory_map: Mapping[str, tuple[str, ...]]`（`.md`→`docs/`；`.c/.h`→`lab/`、`src/`；`.py`→`backend/`、`scripts/`、`lab/`；图片→`assets/`、`docs/assets/`）
  9. `hard_dangerous_patterns: tuple[PatternSpec, ...]`（覆盖 `code-004/005/006`）
  10. `suspicious_patterns: tuple[PatternSpec, ...]`（覆盖 `code-007`）
  11. `secret_patterns: tuple[PatternSpec, ...]`（覆盖 `sens-003/004/005/006`）
  12. `placeholder_context_words: tuple[str, ...] = ("示例","占位","demo","example","sample","mock","xxxx")`
  13. `binary_extensions: tuple[str, ...]`（design 2.5.4（3）全部扩展名）
  14. `naming_chinese_mode: str = "仅建议"`（固定不可改）
  15. `output_language: str = "zh-CN"`（固定不可改）
- **验收标准**：
  - `RuleConfig` 为冻结 dataclass，映射字段存为不可变结构，运行期不可被模块篡改。
  - `PatternSpec.pattern` 必须是已编译的 `re.Pattern[str]`；`language` 只允许 `python`/`c`/`any`。
  - 高危特征 `level` 为"必须修改"，可疑特征 `level` 为"优化建议"；`sens-003`/`sens-004` 的 `exemptable=False`。
  - `DEFAULT_CONFIG` 与 `default_config()` 返回内容等价，且调用方修改返回值不影响全局常量。
  - 基础清单不可为空：`hard_dangerous_patterns` 至少覆盖 `gets`、`strcpy`、`strcat`、`sprintf`、`scanf("%s")`、`eval(`、`exec(`、shell 拼接。

### 3.2 配置合并、校验与回退

- [ ] 完成 3.2 配置合并、校验与回退

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/config.py`
- **函数签名**：
```python
def config_from_mapping(
    data: Mapping[str, object],
    base: RuleConfig | None = None,
) -> ConfigBuildResult: ...

def load_config_file(
    path: str | Path,
    base: RuleConfig | None = None,
) -> ConfigBuildResult: ...

def build_config(
    *,
    overrides: Mapping[str, object] | None = None,
    config_file: str | Path | None = None,
) -> ConfigBuildResult: ...
```
- **验收标准**：
  - 优先级：`overrides` > `config_file` > `DEFAULT_CONFIG`（design 2.8.2）。
  - 类型错误（字符串传给浮点字段）→ 该项回退默认，并追加中文 warning：`配置项 <名称> 取值非法，已使用默认值`。
  - 阈值倒置（`warn ≥ fail`）→ 两项同时回退默认，不做自动交换，追加 warning。
  - `directory_map` 采用整体替换；缺少 `.md`/`.c`/`.h`/`.py` 任一项时整体回退默认并提示。
  - `hard_dangerous_patterns`/`secret_patterns` 采用"默认项 + 追加项"，不允许通过配置删除基础项。
  - 配置文件不存在/非 UTF-8/非 JSON 对象 → 回退默认 + 中文 warning，不抛异常。
  - 未知字段忽略并提示；`naming_chinese_mode` 传入非"仅建议"、`output_language` 传入非 `zh-CN` → 拒绝并回退，追加提示。
  - `warnings` 必须可被 `engine` 原样并入 `CheckReport.warnings`（spec 5.6.1 第 10 条）。
  - 配置解析不得读取仓库内被扫描文件（只读显式 `config_file`）。

### 3.3 特征清单与规则标识绑定

- [ ] 完成 3.3 特征清单与规则标识绑定

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/config.py`
- **验收标准**：
  - `hard_dangerous_patterns` 中每条 `PatternSpec.rule_id` 与判定一一对应：C 类为 `code-004`、Python `eval/exec` 为 `code-005`、shell 拼接为 `code-006`。
  - `suspicious_patterns` 统一绑定 `code-007`，覆盖 `while(1)`/`while(true)`/`for(;;)`、`os.system(`、`subprocess`、裸 `except:`、魔法数字。
  - `secret_patterns` 绑定：PEM 私钥 `sens-003`、已知令牌 `sens-004`、明文密码/连接串 `sens-005`、高熵/长 hex/占位 `sens-006`。
  - `PatternSpec.message` 与 `PatternSpec.suggestion` 均为中文，长度满足 `Finding` 约束（`message` 8～200、`suggestion` ≤ 300）。
  - 正则使用函数名边界，避免 `ast.literal_eval`、`model.eval()`、`subprocess.run([...])` 误报（design 2.5.2（3）边界控制）。

---

## 4. 变更清单解析

**依赖**：T02
**目标**：实现 spec 5.1.1 第 1～7、10 条，产出 `ChangeEntry` 与 `UnparsedLine`，全程不访问文件系统。

### 4.1 逐行解析与状态归一化

- [ ] 完成 4.1 逐行解析与状态归一化

- **创建文件（完整相对路径）**：`backend/app/core/rules/common/manifest.py`
- **函数签名**：
```python
class ManifestReadError(Exception): ...

def parse_manifest(manifest_text: str) -> ManifestParseResult: ...

def parse_manifest_line(
    line: str,
    line_no: int,
) -> ChangeEntry | UnparsedLine | None: ...

def normalize_path(raw_path: str) -> str: ...

def has_escaping_segments(normalized_path: str) -> bool: ...
```
- **验收标准**：
  - 行格式：首个非空白字符为 `A/M/D`（大小写不敏感）且其后紧跟一个及以上空格或制表符；其余内容整体作为路径。
  - 状态 `X`/`Y`/数字等 → 返回 `UnparsedLine(line_no, raw, "未知状态：X")`。
  - 只有状态无路径、路径为空或全空白 → `UnparsedLine`，原因为"缺少文件路径"。
  - 空白行、仅空白行、以 `#` 开头（允许前导空白）的行 → 返回 `None`，不进入任何列表、不计入统计。
  - 小写 `a/m/d` 与大写完全等价，归一化为 `ChangeStatus` 大写值。
  - `normalize_path`：去首尾空白 → `\`→`/` → 反复去除 `./` 前缀 → 折叠重复 `/` → 消除 `.` 段；保留中文、大小写、扩展名。
  - `normalize_path` 不调用 `os.path.realpath`、不 `stat`、不 `open`。
  - `has_escaping_segments` 仅判断归一化后是否仍含 `..` 段。
  - `parse_manifest` 的 `entries` 保持首次出现顺序，`unparsed_lines` 按行号升序。
  - 单行 `raw` ≤ 500 字符，超出截断；`line_no` 从 1 开始。

### 4.2 重复路径合并与删除状态约束

- [ ] 完成 4.2 重复路径合并与删除状态约束

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/manifest.py`
- **函数签名**：
```python
def merge_entries(entries: Sequence[ChangeEntry]) -> tuple[ChangeEntry, ...]: ...
```
- **验收标准**：
  - 以归一化路径为键合并；同一路径多次出现只保留 1 个条目。
  - 状态取最后一次出现；`duplicate_count` 累加（最小 1）。
  - `line_no` 保留**首次**出现行号（spec 6.1 第 3 条）。
  - `merge_entries` 输出顺序为首次出现顺序（后续由 engine 显式排序）。
  - 状态为 `D` 的条目只保留路径、状态、行号信息，不携带任何内容读取标记；解析阶段不对 D 做任何文件系统访问。
  - 非法行不得被当作路径片段访问文件系统（spec 5.1.1 第 10 条）。

### 4.3 清单文件读取与编码回退

- [ ] 完成 4.3 清单文件读取与编码回退

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/manifest.py`
- **函数签名**：
```python
def load_manifest_text(manifest_path: str | Path) -> str: ...
```
- **验收标准**：
  - 按 UTF-8 读取，去除 BOM；UTF-8 失败回退 GB18030；两者均失败抛 `ManifestReadError`。
  - 统一 CRLF/CR 为 `\n`。
  - 文件不存在、无权限、路径为目录 → 抛 `ManifestReadError`，异常消息为中文且包含原路径（供 `run_check_file` 生成"无法读取变更清单：<路径>，请确认文件存在且可读"）。
  - `ManifestReadError` 不携带不可序列化对象；`str(exc)` 即为可展示中文原因。
  - 仅使用 `r`/`rb` 只读模式。

---

## 5. 只读文件访问与安全沙箱

**依赖**：T02、T03
**目标**：实现"单文件单次读取"、路径越界拦截、编码回退与二进制判定，是 spec 4.1 第 3、4 条与 4.3 第 3 条的唯一落点。

### 5.1 路径沙箱与解析结果

- [ ] 完成 5.1 路径沙箱与解析结果

- **创建文件（完整相对路径）**：`backend/app/core/rules/common/file_io.py`
- **函数/类型签名**：
```python
class ReadErrorKind(Enum): ...

@dataclass(frozen=True, slots=True)
class ResolvedPath:
    relative_path: str
    absolute_path: Path | None
    is_safe: bool
    error_kind: ReadErrorKind

def resolve_repo_path(
    repo_root: str | Path,
    relative_path: str,
) -> ResolvedPath: ...
```
- **验收标准**：
  - `ReadErrorKind` 至少覆盖：无错误、路径越界、文件不存在、无权限、编码错误、非法路径。
  - 拒绝以 `/` 开头、`^[A-Za-z]:` 盘符、`^//` UNC 的路径。
  - 归一化后仍含 `..` 段 → 判定越界。
  - 合法候选路径经 `realpath` 后与 `realpath(repo_root)` 做 `commonpath` 比较；Windows 下双方 `casefold()` 后比较。
  - 符号链接指向仓库外 → 判定越界。
  - 非法路径返回 `is_safe=False`、`absolute_path=None`，且**不产生任何 `stat`/`open` 调用**。
  - 仓库根本身不存在/不是目录时，所有路径判定为不安全，由 `engine` 在 P0 阶段先行拦截。
  - 不写文件、不联网、不导入第三方包。

### 5.2 文件快照、编码回退与二进制判定

- [ ] 完成 5.2 文件快照、编码回退与二进制判定

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/file_io.py`
- **函数/类型签名**：
```python
@dataclass(frozen=True, slots=True)
class TextReadResult:
    text: str | None
    error_kind: ReadErrorKind
    error_message: str | None

class FileSnapshot:
    def __init__(
        self,
        repo_root: Path,
        relative_path: str,
        resolved: ResolvedPath,
        binary_extensions: Sequence[str],
    ) -> None: ...

    @property
    def path(self) -> str: ...
    @property
    def size(self) -> int: ...
    @property
    def is_binary(self) -> bool: ...
    @property
    def read_error(self) -> str | None: ...
    def text(self) -> TextReadResult: ...

def create_snapshot(
    repo_root: str | Path,
    relative_path: str,
    config: RuleConfig,
) -> FileSnapshot: ...

def read_text_from_disk(
    absolute_path: Path,
    *,
    max_bytes: int | None = None,
) -> TextReadResult: ...

def is_binary_file(
    absolute_path: Path,
    binary_extensions: Sequence[str],
    *,
    sample_size: int = 8192,
) -> bool: ...
```
- **验收标准**：
  - `size` 首次访问只 `stat` 一次并缓存；文件不存在/无权限时返回 0 并记录 `read_error`。
  - `text()` 首次调用才读取，读取后缓存；同一实例多次调用不再触发磁盘读取。
  - 读取流程：`rb` 读入 → 去除 UTF-8 BOM → `utf-8` 严格解码 → 失败回退 `gb18030` → 再失败返回 `TextReadResult(text=None, error_kind=ENCODING_ERROR, error_message="文件编码无法识别，建议另存为 UTF-8 后重试")`。
  - `is_binary` 先按 `binary_extensions` 判断，再读首 `sample_size` 字节检测 `\x00`；二进制不进入文本缓存，不读取全文。
  - 任何读取失败都返回结果对象，不抛异常（spec 4.2 第 2 条）。
  - 仅使用 `r`/`rb` 模式；不调用 `write`/`unlink`/`rename`/`makedirs`。
  - > 5 MB 文件不得整体读入内存：`text()` 支持分块上限或明确的分块读取路径，供 `sensitive`/`code_scan` 使用。
  - `read_text_from_disk` 只接受已通过沙箱的绝对路径，供快照与清单读取复用。

### 5.3 模块上下文注入

- [ ] 完成 5.3 模块上下文注入

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/file_io.py`
- **函数/类型签名**：
```python
@dataclass(frozen=True, slots=True)
class CheckContext:
    repo_root: Path
    config: RuleConfig
    module_name: str
    snapshot: Callable[[str], FileSnapshot]
```
- **验收标准**：
  - `CheckContext` 只能由 `engine` 构造并注入四模块；模块内不得自行构造或替换 `snapshot`。
  - `snapshot(relative_path)` 对同一路径返回同一 `FileSnapshot` 实例（缓存），保证四模块共享一次读取。
  - `file_io` 允许导入 `common.config`，`common.config` 不得反向导入 `file_io`（design 2.4.4）。
  - `D` 状态条目不得调用 `snapshot`（由模块与 engine 双重保证）。

---

## 6. 命名与目录归属检查（`naming.py`）

**依赖**：T03、T05（并行组 C）
**目标**：实现 spec 5.2.1 第 1～10 条，全部判定只依据路径与扩展名，D 状态零 I/O。

### 6.1 模块入口与公开函数骨架

- [ ] 完成 6.1 模块入口与公开函数骨架

- **创建文件（完整相对路径）**：`backend/app/core/rules/naming.py`
- **函数签名**：
```python
def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def check_naming(path: str, config: RuleConfig) -> tuple[Finding, ...]: ...

def check_directory(path: str, config: RuleConfig) -> tuple[Finding, ...]: ...

def suggest_file_name(file_name: str) -> str: ...

def suggest_directory(path: str, config: RuleConfig) -> str | None: ...

def is_test_file(path: str) -> bool: ...
```
- **验收标准**：
  - `check` 对 `A/M/D` 均执行，组合 `check_naming` 与 `check_directory` 后做同类合并，返回 `ModuleResult`。
  - `check` 内**不得**调用 `ctx.snapshot()`；D 状态不得触发任何文件系统访问。
  - 每条 `Finding.file_path` 等于 `entry.path`，`line_no` 固定 `None`。
  - 只允许导入 `common.models`、`common.file_io`、标准库 `re`/`unicodedata`；`RuleConfig` 仅作 `TYPE_CHECKING` 导入。
  - 不得导入 `engine` 或其他三个检查模块。

### 6.2 文件名硬规则（`naming-001`/`naming-002`）

- [ ] 完成 6.2 文件名硬规则（`naming-001`/`naming-002`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/naming.py`
- **验收标准**：
  - `naming-001`（必须修改）：文件名含 `< > : " | ? *`、U+0000–U+001F 控制字符或以 `.` 结尾；建议给出把非法字符替换为 `_` 后的完整推荐文件名。
  - `naming-002`（必须修改）：文件名（含扩展名）Unicode 字符数 > 120；建议缩短至 60 字符以内并给出截断示例。
  - 边界：120 字符不报、121 字符报；按字符计数而非字节。
  - 同文件同一规则最多 1 条，不得逐字符重复报错。
  - 仅检查文件名（basename），不检查目录名中的非法字符。

### 6.3 命名风格与中文引导（`naming-003`/`naming-004`）

- [ ] 完成 6.3 命名风格与中文引导（`naming-003`/`naming-004`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/naming.py`
- **验收标准**：
  - `naming-003`（优化建议）：文件名含大写字母、空格、连字符、连续下划线或非 ASCII 非中文符号；示例 `UART Demo-v2.C` → `uart_demo_v2.c`。
  - `naming-004`（优化建议，禁止升级）：文件名或路径段含中文；示例 `docs/lab03_串口通信实验.md` → `docs/lab03_serial_communication.md`，建议文本说明跨平台工具链/命令行/自动化脚本不便。
  - `naming-003` 与 `naming-004` 同时命中时只输出 1 条优化建议，建议同时包含"英文/拼音 + 下划线"与完整目标路径。
  - 纯中文文件名最多 1 条优化建议，绝不产生"必须修改"（spec 5.2.1 第 10 条）。
  - `suggest_file_name` 永不返回空串，返回可直接采用的推荐文件名（保留下划线小写风格与正确扩展名）。

### 6.4 目录归属（`naming-005`/`naming-006`）

- [ ] 完成 6.4 目录归属（`naming-005`/`naming-006`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/naming.py`
- **验收标准**：
  - `naming-005`（必须修改）三条判定：
    1. `.c/.h/.py` 位于 `docs/` 下；
    2. `.md` 位于 `backend/`、`src/`、`lab/` 下；
    3. 测试文件（`test_*.py`、`*_test.py`、路径含 `tests/`）不在 `backend/tests/` 下。
  - `naming-006`（优化建议）三条判定：源码在仓库根、图片不在 `assets/` 或 `docs/assets/`、实验报告类 `.md`（文件名含 `lab`+数字/`实验`/`报告`/`report`）不在 `docs/`。
  - 目录前缀按路径段匹配，避免 `backendx/` 误判为 `backend/`。
  - 无扩展名 → 跳过目录判定；扩展名不在映射表（如 `.xyz`）→ 不输出目录问题。
  - `naming-005` 与 `naming-006` 同时命中 → 只输出 `naming-005`（必须修改优先）。
  - `suggest_directory` 返回推荐目录（如 `lab/uart/`）；未命中映射表返回 `None`。
  - `suggestion` 必须含目标路径，示例：`docs/uart_demo.c` → `lab/uart/uart_demo.c`。
  - 每文件最多 4 条（001、002、合并风格 1 条、合并目录 1 条）。

---

## 7. 代码注释与高危写法检查（`code_scan.py`）

**依赖**：T03、T05（并行组 C）
**目标**：实现 spec 5.3.1 第 1～10 条，覆盖 `.py`/`.c`/`.h`，`.h` 结果全部降级为优化建议。

### 7.1 模块入口、语言识别与代码视图

- [ ] 完成 7.1 模块入口、语言识别与代码视图

- **创建文件（完整相对路径）**：`backend/app/core/rules/code_scan.py`
- **函数签名**：
```python
def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def detect_language(path: str) -> str: ...

def build_code_view(text: str, language: str) -> str: ...
```
- **验收标准**：
  - `detect_language`：`.py` → `python`；`.c`/`.h` → `c`；其他 → `none`。
  - `check` 仅处理 `A/M` 的 `.py`/`.c`/`.h`；`D`、其他扩展名直接返回 `ModuleResult(())`，不创建快照。
  - 二进制或编码失败 → 返回 `skip_reason="文件内容无法解码，已跳过代码检查"`，不产生内容问题。
  - 体积 > `code_scan_max_mb` → 仅产出 `code-008` 优化建议，不执行 AST/正则扫描，不重复报注释类问题。
  - `build_code_view`：状态机把 `//`、`/* */`、`#`、单双引号字符串、Python 三引号字符串替换为空格，**保留换行符**，输出长度与原文一致，行号不偏移。
  - `build_code_view` 必须正确处理转义字符与跨行字符串，避免提前结束视图。
  - 只允许导入 `common.models`、`common.file_io`、标准库 `ast`/`re`/`time`；不得导入其他检查模块或 `engine`。

### 7.2 Python 源码扫描（`code-001`/`code-002`/`code-003`）

- [ ] 完成 7.2 Python 源码扫描（`code-001`/`code-002`/`code-003`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/code_scan.py`
- **函数签名**：
```python
def scan_python_source(
    text: str,
    file_path: str,
    config: RuleConfig,
    *,
    downgrade_level: bool = False,
) -> tuple[Finding, ...]: ...
```
- **验收标准**：
  - `ast.parse` 识别模块 docstring：首个非空语句为字符串常量则满足，否则 `code-001`（优化建议）。
  - 遍历 `FunctionDef`/`AsyncFunctionDef`（含类方法）：公开函数（不以 `_` 开头）缺 docstring → `code-002`（必须修改）；类方法同样适用。
  - 非公开函数且函数体 ≤ 10 行缺紧邻注释 → `code-003`（优化建议）。
  - docstring 必须位于函数体第一处语句；函数体内零散注释不计为函数注释。
  - `ast.parse` 失败（语法不完整）→ 跳过全部函数注释判定，仅保留文本级高危/可疑匹配，不产生误报。
  - 全部 `code-002`/`code-003` 必须携带 `line_no`（函数定义起始行从 1 开始）。
  - 中文 docstring/注释视为满足要求，不因语言报错。
  - `downgrade_level=True` 时全部"必须修改"降为"优化建议"。

### 7.3 C 源码扫描（`code-001`/`code-002`/`code-003`）

- [ ] 完成 7.3 C 源码扫描（`code-001`/`code-002`/`code-003`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/code_scan.py`
- **函数签名**：
```python
def scan_c_source(
    text: str,
    file_path: str,
    config: RuleConfig,
    *,
    downgrade_level: bool = False,
) -> tuple[Finding, ...]: ...
```
- **验收标准**：
  - 文件头：去除 BOM 与前导空行后，首个非空块为 `//` 或 `/* */` 注释则满足，否则 `code-001`（优化建议）。
  - 函数识别：正则匹配"返回类型/指针 + 函数名 + 参数列表 + `{`"，排除 `if/for/while/switch/return/sizeof/struct/union/enum/typedef` 与行首 `#define`。
  - 通过大括号计数确认函数体结束；无法配对则跳过该片段（宁可漏报不误报）。
  - `main` 与非 `static` 函数缺紧邻注释 → `code-002`（必须修改）；注释须位于定义之前紧邻位置（允许间隔空行），函数体内注释不算。
  - `static` 且函数体 ≤ 10 行缺注释 → `code-003`（优化建议）。
  - 支持 `//`、`/* ... */`、`/** ... */` 与 Doxygen 风格。
  - 每条问题携带行号；中文注释视为满足。
  - `downgrade_level=True` 时全部"必须修改"降为"优化建议"。

### 7.4 高危写法（`code-004`/`code-005`/`code-006`）

- [ ] 完成 7.4 高危写法（`code-004`/`code-005`/`code-006`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/code_scan.py`
- **验收标准**：
  - `code-004`（必须修改，C）：`gets(`、`strcpy(`、`strcat(`、`sprintf(`、`scanf("%s")`；建议分别给出 `fgets`、`snprintf`、`strncpy` + 补 `\0`、`scanf("%99s")`。
  - `code-005`（必须修改，Python）：`eval(`、`exec(`；排除 `ast.literal_eval`、`model.eval()` 等误匹配（函数名边界）。
  - `code-006`（必须修改，任意语言）：字符串拼接（`+`、f-string、`%`、`.format`）结果传入 `os.system`/`os.popen`/`subprocess(shell=True)`；建议 `subprocess.run([...], shell=False)` 或 `shlex.quote`。
  - `subprocess.run(["固定命令", 参数])` 不报。
  - 全部匹配只在 `build_code_view` 结果上执行：注释、docstring、普通字符串中的关键字不报（spec 5.3.3 第 4 条）。
  - 每条命中必须带原始行号；同一位置同一规则只报 1 条。

### 7.5 可疑写法、文件级说明与聚合（`code-007`/`code-008`）

- [ ] 完成 7.5 可疑写法、文件级说明与聚合（`code-007`/`code-008`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/code_scan.py`
- **验收标准**：
  - `code-007`（优化建议）：`while(1)`/`while(true)`/`for(;;)`、`os.system(`、`subprocess` 调用、裸 `except:`、同一函数内同一数字字面量重复 ≥3 次或 ≥4 位数字；建议说明退出条件、替代方式与"嵌入式轮询场景可保留"。
  - 魔法数字仅在函数内聚合 1 条。
  - `code-008`（优化建议）：> 5 MB 或内容扫描超预算；仅 1 条说明性建议，`line_no` 允许 `None`。
  - `.h` 文件的所有结果降级为优化建议（`downgrade_level=True`）。
  - 同文件同 `rule_id` 最多 5 条，超出合并为 1 条"另有 N 处同类问题"（使用 `merge_findings`）。
  - 输出按行号升序；无行号条目排末尾。

---

## 8. Markdown 链接格式检查（`link_check.py`）

**依赖**：T03、T05（并行组 C）
**目标**：实现 spec 5.4.1 第 1～11 条，只做格式判定，不联网、不读取链接目标。

### 8.1 代码块剔除与链接提取

- [ ] 完成 8.1 代码块剔除与链接提取

- **创建文件（完整相对路径）**：`backend/app/core/rules/link_check.py`
- **函数/类型签名**：
```python
@dataclass(frozen=True, slots=True)
class LinkRecord:
    line_no: int
    raw: str
    target: str
    kind: str
    text: str | None = None
    reference_id: str | None = None

def strip_code_blocks(text: str) -> str: ...

def extract_links(text: str) -> tuple[LinkRecord, ...]: ...
```
- **验收标准**：
  - `strip_code_blocks` 识别 ``` 与 ~~~ 围栏（含 info string；闭合标记字符相同且长度 ≥ 开启长度），块内全部行替换为空行，**保留原行号**。
  - 剔除行内反引号代码片段，避免示例语法被当链接。
  - `extract_links` 识别五类：行内 `[文本](目标 "标题")`、图片 `![说明](目标)`、引用式 `[文本][标识]`/`[标识][]`、定义 `[标识]: 目标`、裸 `http(s)://...`。
  - `kind` 仅取 `inline`/`image`/`reference`/`definition`/`bare`；`raw` 为原始片段，后续截断到 ≤ 60 字符写入 `excerpt`。
  - 换行拆开的合法续行正常解析；结构确实不成立时才由校验阶段报错。
  - 不读取 `target` 指向的文件，不发起网络请求。

### 8.2 结构与协作适配校验（`link-001`～`link-007`）

- [ ] 完成 8.2 结构与协作适配校验（`link-001`～`link-007`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/link_check.py`
- **函数签名**：
```python
def validate_links(
    links: Sequence[LinkRecord],
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...
```
- **验收标准**：
  - `link-001`（必须修改）：目标为空或仅空白，如 `[说明]()`。
  - `link-002`（必须修改）：`]`/`)` 缺失或嵌套错乱；建议标注缺失的右括号位置并给出合并为一行的示例。
  - `link-003`（必须修改）：引用式标识在全文件无定义（定义可出现在文末，需先全文件收集）；快捷式 `[标识]` 仅在存在定义时视为链接，不误报。
  - `link-004`（优化建议）：盘符路径、`file:///`、含本机用户目录；建议改为 `./lab03.md` 相对路径。
  - `link-005`（必须修改）：目标含空格且未被 `<...>` 包裹；建议 `%20` 编码或 `<>` 包裹；`<...>` 内空格合法不报。
  - `link-006`（优化建议）：`http://`、`localhost`/`127.0.0.1`/内网 IP、链接文本为空；同文件同类合并 1 条。
  - `link-007`（优化建议）：目标含未编码中文；或 `../` 解析后越出仓库根；中文锚点（如 `./实验指导.md#第三部分`）不得报必须修改，最多 1 条建议。
  - 同一行同一链接只报级别最高的一条（必须修改优先）。
  - 每条问题必须带 `line_no`（来自 `LinkRecord.line_no`），`excerpt` ≤ 60 字符且为链接原文片段。

### 8.3 模块入口与大批量聚合（`link-008`）

- [ ] 完成 8.3 模块入口与大批量聚合（`link-008`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/link_check.py`
- **函数签名**：
```python
def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...
```
- **验收标准**：
  - 仅处理 `A/M` 的 `.md`；`D`、非 Markdown 返回空结果且不创建快照。
  - 二进制/编码失败 → `skip_reason="Markdown 内容无法解码，已跳过链接检查"`。
  - 链接总数 > `link_max_per_file`（默认 200）→ 继续检查，并追加 1 条 `link-008`（优化建议），内容为"该文件共 N 条链接，其中 M 条存在格式问题"，建议拆分文档。
  - 200 条不报、201 条报。
  - 同文件同 `rule_id` 优化建议超过 5 条 → 合并为 1 条"另有 N 处同类问题"，保留前 5 个行号。
  - 只允许导入 `common.models`、`common.file_io`、标准库 `re`/`ipaddress`；不导入其他模块或 `engine`。

---

## 9. 敏感信息与大文件检查（`sensitive.py`）

**依赖**：T03、T05（并行组 C）
**目标**：实现 spec 5.5.1 第 1～10 条与 5.5.3 异常场景，凭据必须脱敏。

### 9.1 体积分级（`sens-001`/`sens-002`）

- [ ] 完成 9.1 体积分级（`sens-001`/`sens-002`）

- **创建文件（完整相对路径）**：`backend/app/core/rules/sensitive.py`
- **函数签名**：
```python
def check_file_size(
    size_bytes: int,
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...
```
- **验收标准**：
  - `size_bytes > large_file_fail_mb * 1024 * 1024` → `sens-002`（必须修改），描述附当前体积（MB，保留 1 位小数），建议移出仓库/外部存储/Git LFS。
  - `size_bytes > large_file_warn_mb * 1024 * 1024` 且未超失败阈值 → `sens-001`（优化建议），建议压缩/拆分/Git LFS。
  - 恰好 1 MB、恰好 5 MB 按"未超过"处理（仅 `>` 触发）。
  - 体积比较使用字节整数，阈值换算一次后取整，不使用浮点比较。
  - `line_no=None`、`excerpt=None`。

### 9.2 脱敏与教学豁免

- [ ] 完成 9.2 脱敏与教学豁免

- **修改文件（完整相对路径）**：`backend/app/core/rules/sensitive.py`
- **函数签名**：
```python
def mask_secret(value: str) -> str: ...

def is_placeholder_context(
    line: str,
    start: int,
    end: int,
    config: RuleConfig,
) -> bool: ...
```
- **验收标准**：
  - `mask_secret`：长度 > 4 → `value[:4] + "****"`；长度 ≤ 4 → `"****"`；禁止返回原文。
  - `is_placeholder_context`：检查 `[start, end)` 命中位置前后各 80 字符内是否含 `placeholder_context_words` 任一词，返回布尔值。
  - `sens-003`（PEM 私钥）与 `sens-004`（已知真实令牌格式）**不得**调用豁免降级。
  - `sens-004`/`sens-005`/`sens-006` 命中且处于示例上下文 → 降为优化建议。
  - 脱敏后的值必须用于 `message`、`suggestion`、`excerpt` 全部字段；原文只允许存在于局部变量。

### 9.3 凭据特征扫描（`sens-003`～`sens-006`）

- [ ] 完成 9.3 凭据特征扫描（`sens-003`～`sens-006`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/sensitive.py`
- **函数签名**：
```python
def scan_secrets(
    text: str,
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...
```
- **验收标准**：
  - `sens-003`（必须修改）：PEM 私钥头 `-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----`；建议立即移除并轮换。
  - `sens-004`（必须修改）：`AKIA/ASIA`+16 位、`ghp_/gho_/ghu_/ghs_/ghr_`、`github_pat_`、`glpat-`、`xox[baprs]-`、`sk-`+20 位以上、`AIza`+35 位；仅在文本行匹配，不匹配二进制。
  - `sens-005`（必须修改）：`password/passwd/pwd/token/secret/api_key/apikey/access_key` 等字段被赋非空真实字面量；数据库连接串 `scheme://user:pass@host`。
    - 排除：空值、`${VAR}`、`os.getenv(...)`、`<...>`、`{{...}}`、`your_`、`****`、"请输入"。
  - `sens-006`（优化建议）：长度 ≥ 32 且字符类别 ≥ 3、香农熵 ≥ 3.5 的高熵串；长度 ≥ 32 的十六进制串；凭据变量被赋空值/占位符。
  - 与 `sens-004`/`sens-005` 同时命中时以必须修改为准，不重复报 `sens-006`。
  - 同文件同规则聚合为 1 条：列出前 3 个命中行号，其余显示"共 N 处"；`line_no` 取首次命中行。
  - `excerpt` 必须已脱敏。
  - 不对二进制内容做文本匹配；不调用外部服务验证密钥。

### 9.4 模块入口、二进制跳过与超时（`sens-007`）

- [ ] 完成 9.4 模块入口、二进制跳过与超时（`sens-007`）

- **修改文件（完整相对路径）**：`backend/app/core/rules/sensitive.py`
- **函数签名**：
```python
def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...
```
- **验收标准**：
  - 仅处理 `A/M`；`D` 直接返回空结果，不 `stat`、不读取。
  - 先执行体积检查，再判定二进制：扩展名命中 `binary_extensions` 或首 8 KB 含 `\x00` → 仅保留体积结论，不进入文本扫描。
  - 文本扫描按 64 KB 分块，每块检查 1 s 预算（`large_text_scan_timeout_s`）；超时保留体积结论并产出 `sens-007`（优化建议，"文件过大，仅完成体积检查"）。
  - 文件不存在/无权限 → 返回 `skip_reason="无法获取文件信息，已跳过"`。
  - 空文件或仅空白 → 不产生体积与敏感信息问题。
  - 每文件凭据问题按规则聚合；不得输出完整凭据、不得写日志文件。
  - 只允许导入 `common.models`、`common.file_io`、标准库 `re`/`time`/`math`（或等价标准库）；不导入其他模块或 `engine`。

---

## 10. 中文摘要与 JSON 序列化（`common/report.py`）

**依赖**：T02
**目标**：实现 spec 5.6.1 第 6、7 条与 design 2.6.4、2.6.5。

### 10.1 中文终端摘要

- [ ] 完成 10.1 中文终端摘要

- **创建文件（完整相对路径）**：`backend/app/core/rules/common/report.py`
- **函数签名**：
```python
def render_text(report: CheckReport) -> str: ...
```
- **验收标准**：
  - 开头固定为 `RepoGuard 规则检查结果`，随后输出条目总数、问题总数、必须修改数、优化建议数。
  - 必须包含引导语"请先处理「必须修改」项，再根据时间采纳「优化建议」。"。
  - 按文件分组展示，同一文件内"必须修改"在前、"优化建议"在后，遵循 report 中已排序的顺序，不重排。
  - 每条问题展示"第 <行号> 行：<描述>"与"修改建议：<建议>"；无行号时不输出"第 N 行"。
  - 未完成检查的文件、"模块降级说明"、"提示"三节仅在数据非空时出现；降级时必须以"结果可能不完整"结尾。
  - 无问题时输出"未发现问题"；空清单输出"变更清单为空，请确认是否已生成改动列表"。
  - 全部中文；不输出 ANSI 颜色码、英文堆栈、英文规则名作为主提示（`rule_id` 可在括号内附带）。
  - 不修改入参对象、不写文件。

### 10.2 字典与 JSON 序列化

- [ ] 完成 10.2 字典与 JSON 序列化

- **修改文件（完整相对路径）**：`backend/app/core/rules/common/report.py`
- **函数签名**：
```python
def report_to_dict(report: CheckReport) -> dict[str, object]: ...

def report_to_json(report: CheckReport) -> str: ...
```
- **验收标准**：
  - 输出键名与 design 2.6.5 完全一致：`status`、`summary`、`files`、`unparsed_lines`、`degraded_modules`、`warnings`。
  - 枚举转中文值：`必须修改`/`优化建议`、`正常`/`部分降级`/`输入错误`；状态转单字母 `A/M/D`。
  - 可选字段缺失时输出 `null`，不省略键；空结果仍保留完整骨架。
  - `report_to_json` 使用 `json.dumps(..., ensure_ascii=False, indent=2)`，中文不转义。
  - 不含时间戳、绝对路径、主机名、异常对象。
  - 序列化失败时回退为仅含 `level`/`file_path`/`message`/`suggestion` 的最小结构，仍返回可解析 JSON；由 `engine` 追加 warning"部分附加信息未能输出"。
  - 只读 `CheckReport`，不修改对象、不联网、不写文件。

---

## 11. 汇总入口与模块调度（`engine.py`）

**依赖**：T03、T04、T05、T06、T07、T08、T09、T10
**目标**：实现 spec 5.1、5.6 全部业务规则，成为唯一公共入口。

### 11.1 编程入口 `run_check`

- [ ] 完成 11.1 编程入口 `run_check`

- **创建文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **函数签名**：
```python
def run_check(
    manifest_text: str,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...
```
- **验收标准**：
  - 完整执行 P0～P10：参数校验 → 清单加载 → 逐行解析 → 归一化与合并 → 空清单判定 → 快照构建 → 四模块调度 → 分组 → 排序 → 统计与状态 → 渲染结果返回。
  - P0：`repo_root` 不存在或不是目录 → `status=输入错误`、`summary` 全零、`warnings` 含"仓库根目录不存在，请检查路径参数"，不进入文件检查。
  - P4：无有效条目 → 结构完整空报告 + warning"变更清单为空，请确认是否已生成改动列表"。
  - 任何业务异常均转为报告字段，不向调用方抛出；仅 `MemoryError`/`KeyboardInterrupt`/`SystemExit` 不拦截。
  - 相同输入与仓库内容，`report_to_json()` 输出逐字节一致（spec 4.2 第 4 条）。
  - 不修改仓库文件；不发起网络请求；默认不写任何文件。
  - `config=None` 时使用 `default_config()`；配置 warnings 并入报告。

### 11.2 模块调度与异常隔离

- [ ] 完成 11.2 模块调度与异常隔离

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **验收标准**：
  - 按 design 2.6.2 调度：`naming` 处理 A/M/D；`code_scan` 处理 A/M 的 `.py/.c/.h`；`link_check` 处理 A/M 的 `.md`；`sensitive` 处理 A/M 全部文件。
  - D 状态不得创建 `FileSnapshot`；仅 `naming` 收到该条目。
  - 每个模块独立 `try/except Exception`；模块异常 → 追加 `DegradedModule(模块中文名, "执行异常，结果可能不完整")`，其余模块继续。
  - 模块中文名映射固定：`naming → 命名与目录检查`、`code_scan → 代码检查`、`link_check → 链接检查`、`sensitive → 敏感信息与大文件检查`。
  - 单文件读取/判定异常 → 该文件 `skip_reason`，不降级模块；同一文件同一原因只记录一次。
  - `FileSnapshot` 由 engine 统一创建并缓存，四模块共享；同一路径只创建一次。
  - 路径越界 → 文件分组 `skip_reason="路径超出仓库范围，已跳过：<路径>"`；内容类模块全部跳过，`naming` 仍以路径字符串执行。
  - A/M 文件不存在 → `skip_reason="文件不存在，已跳过内容检查"`；编码失败 → `skip_reason="文件编码无法识别，建议另存为 UTF-8 后重试"`。
  - 四模块中任一模块降级 → `status=部分降级`。

### 11.3 分组、排序、统计与状态

- [ ] 完成 11.3 分组、排序、统计与状态

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **验收标准**：
  - 以归一化路径为唯一键分组，每文件只出现一次；分组携带 `status`、`findings`、`skip_reason`、`duplicate_count`。
  - 无问题的条目也保留文件分组（用于展示状态与跳过原因）。
  - 文件按 `file_path` 的 Unicode 码点升序（不使用 `locale`）。
  - 文件内问题排序：`level`（必须修改=0，优化建议=1）→ `line_no` 升序（`None` 视为无穷大排末尾）→ `rule_id` 字典序 → `message` 字典序。
  - `unparsed_lines` 按行号升序；`degraded_modules` 按 `naming → code_scan → link_check → sensitive` 固定顺序，再按原因字典序。
  - `CheckSummary` 七项统计口径与 design 2.3.2（4）一致；`skipped_file_count` 统计带 `skip_reason` 的分组数（即使同时有问题也计入）。
  - 状态判定：全部模块完成 → `正常`；任一模块降级或序列化回退 → `部分降级`；仓库根非法/清单不可读 → `输入错误`。
  - 调用 `validate_report`；校验失败 → 视为内部异常，降级并输出最小报告，追加中文 warning。

### 11.4 空结果、跳过与降级可见性

- [ ] 完成 11.4 空结果、跳过与降级可见性

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **验收标准**：
  - 无问题 → `files=()`、统计全零、`status=正常`，不得返回 `None` 或省略字段。
  - 全部条目被跳过 → 空问题列表 + 跳过统计 + 摘要提示"本次未完成任何文件检查，请确认清单与仓库路径是否匹配"。
  - 降级模块必须出现在 `degraded_modules`，且 `degraded_module_count` 与长度一致；摘要末尾出现"结果可能不完整"。
  - 无法解析行必须单列在 `unparsed_lines`，`unparsed_line_count` 与长度一致，且不改变 `status`。
  - 不得在报告中输出英文堆栈、不得把多个文件的问题合并成一条、不得在未指定输出路径时写入文件。

### 11.5 清单文件入口 `run_check_file`

- [ ] 完成 11.5 清单文件入口 `run_check_file`

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **函数签名**：
```python
def run_check_file(
    manifest_path: str | Path,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...
```
- **验收标准**：
  - 调用 `load_manifest_text` 读取清单（UTF-8/BOM/GB18030），成功后委托 `run_check`，结果与 `run_check(文件内容, ...)` 完全一致。
  - `ManifestReadError` → `status=输入错误`、`summary` 全零、`warnings` 含"无法读取变更清单：<路径>，请确认文件存在且可读"。
  - 不抛异常；不把异常对象放入报告。

---

## 12. 命令行入口与退出码

**依赖**：T11
**目标**：实现 spec 5.6.1 第 8 条与 design 2.4.3（4.8）。

### 12.1 参数解析器

- [ ] 完成 12.1 参数解析器

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **函数签名**：
```python
def build_arg_parser() -> argparse.ArgumentParser: ...
```
- **验收标准**：
  - 参数固定为：`--manifest`（必填，文件路径或 `-`）、`--repo`（默认 `"."`）、`--format`（`text`/`json`，默认 `text`）、`--output`（默认 `None`）、`--config`（默认 `None`）、`--debug`（`store_true`，默认 `False`）。
  - 参数 `dest` 与 design 2.4.3（4.8）表一致。
  - `build_arg_parser` 只定义参数，不执行检查、不读文件。

### 12.2 CLI 主流程

- [ ] 完成 12.2 CLI 主流程

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **函数签名**：
```python
def main(argv: Sequence[str] | None = None) -> int: ...
```
- **验收标准**：
  - `argv=None` 时读取 `sys.argv[1:]`；返回 `ExitCode` 的整数值。
  - `--manifest -` → 从 stdin 读取清单文本并调用 `run_check`；否则调用 `run_check_file`。
  - `--format text` → stdout 输出 `render_text(report)`；`--format json` → 输出 `report_to_json(report)`。
  - `--output` 显式指定时额外写 JSON 到该路径；未指定时只写 stdout，仓库内不产生文件。
  - `--config` 通过 `build_config(config_file=...)` 合并；配置 warnings 进入报告。
  - `--debug` 仅在向 stderr 输出 traceback 时生效，并加"以下为调试信息，可忽略"；正常模式禁止英文堆栈。
  - 输出编码为 UTF-8，中文不转义。
  - 输出文件不可写 → 保留 stdout，追加 warning"无法写入输出文件：<路径>"，退出码按执行异常处理。

### 12.3 退出码计算

- [ ] 完成 12.3 退出码计算

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **函数签名**：
```python
def exit_code_for(report: CheckReport) -> ExitCode: ...
```
- **验收标准**：
  - 优先级固定 `2 > 3 > 1 > 0`：`输入错误` → 2；降级/序列化回退 → 3；存在必须修改 → 1；仅优化建议或无问题 → 0。
  - `main` 必须调用该函数，禁止另写判断。
  - 空清单 → 0；存在必须修改且同时降级 → 3；仓库根不存在 → 2（即使清单中有必须修改）。

### 12.4 模块执行守卫

- [ ] 完成 12.4 模块执行守卫

- **修改文件（完整相对路径）**：`backend/app/core/rules/engine.py`
- **验收标准**：
  - 文件末尾提供 `if __name__ == "__main__": raise SystemExit(main())` 守卫。
  - 在 `backend/` 下执行 `python -m app.core.rules.engine --help` 正常输出中文帮助并退出 0。
  - `engine.py` 不得导入 `app.core.rules` 包根（避免循环依赖），只导入四个兄弟模块与 `common.*`。

---

## 13. 公共门面 `rules/__init__.py`

**依赖**：T02、T03、T10、T11
**目标**：满足 design 2.4.3（4.6）导出契约，保证 `from app.core.rules import run_check, render_text, report_to_json` 可用。

### 13.1 稳定公共 API 再导出

- [ ] 完成 13.1 稳定公共 API 再导出

- **创建文件（完整相对路径）**：`backend/app/core/rules/__init__.py`
- **导出契约**：
```python
__all__: tuple[str, ...] = (
    "run_check", "run_check_file", "render_text",
    "report_to_dict", "report_to_json",
    "CheckReport", "CheckSummary", "FileGroup", "Finding",
    "ChangeEntry", "IssueLevel", "ReportStatus", "ExitCode",
    "RuleConfig", "DEFAULT_CONFIG",
)
```
- **验收标准**：
  - 仅包含 `from app.core.rules.engine import ...`、`from app.core.rules.common.models import ...`、`from app.core.rules.common.config import ...`、`from app.core.rules.common.report import ...`。
  - 不含任何判定逻辑、模块级可变状态、函数定义。
  - 不导出 `common/*` 内部函数、`LinkRecord`、`FileSnapshot`、`CheckContext`。
  - `from app.core.rules import run_check, render_text, report_to_json, RuleConfig, DEFAULT_CONFIG` 全部可导入。
  - `rules/__init__.py` 不得被 `engine.py` 导入。

---

## 14. 样例变更清单与样例仓库

**依赖**：T01（并行组 A，可与 T02～T13 并行）
**目标**：产出 spec 7 第 7 条与 7.1 第 3 条要求的样例资产，覆盖四个检查模块。

### 14.1 样例变更清单

- [ ] 完成 14.1 样例变更清单

- **创建文件（完整相对路径）**：`backend/tests/fixtures/sample_changes.txt`
- **内容要求（UTF-8 无 BOM，行序固定）**：
  1. `# RepoGuard 样例变更清单（UTF-8，用于本地测试）`
  2. `# 状态：A=新增  M=修改  D=删除`
  3. 空行
  4. `A docs/lab03_串口通信实验.md`
  5. `M lab/uart/uart_demo.c`
  6. `A lab/uart/UART Demo-v2.C`
  7. `A docs/uart_demo.c`
  8. `A backend/app/example_config.py`
  9. `M docs/lab02_broken_link.md`
  10. `A assets/large_sample.mp4`
  11. `D notes/old_lab02.md`
  12. `A backend/tests/test_demo.py`
  13. `M lab/uart/uart_demo.c`
  14. `X notes/unknown_status.md`
  15. `M`
- **验收标准**：
  - 同时覆盖 A/M/D、小写状态可选、中文文件名、错误目录、缺注释代码、异常链接、大文件、疑似密钥、空行、注释行、非法状态、只有状态、重复路径。
  - 第 5 与第 13 行为同一路径，用于验证合并（状态 M、`duplicate_count=2`）。
  - 第 14 行进入 `unparsed_lines`（原因"未知状态：X"）；第 15 行进入 `unparsed_lines`（原因"缺少文件路径"）。
  - 文件为 UTF-8 无 BOM、`\n` 换行。

### 14.2 样例仓库最小文件

- [ ] 完成 14.2 样例仓库最小文件

- **创建/修改文件（完整相对路径）**：
  - `demo-repo/docs/lab03_串口通信实验.md`
  - `demo-repo/docs/uart_demo.c`
  - `demo-repo/docs/lab02_broken_link.md`
  - `demo-repo/lab/uart/uart_demo.c`
  - `demo-repo/lab/uart/UART Demo-v2.C`
  - `demo-repo/backend/app/example_config.py`
  - `demo-repo/backend/tests/test_demo.py`
  - `demo-repo/notes/old_lab02.md`（允许不存在，用于 D 状态）
  - `demo-repo/assets/`（目录；`large_sample.mp4` **不提交**）
- **验收标准**：
  - `demo-repo/docs/lab03_串口通信实验.md`：正常中文实验说明 + 1 个正常相对链接，用于 `naming-004` 与链接反例。
  - `demo-repo/docs/uart_demo.c`：与 `lab/uart/uart_demo.c` 内容一致或简化，用于 `naming-005`。
  - `demo-repo/docs/lab02_broken_link.md`：含 `[说明]()`、`[说明](./lab03.md`、`[说明][ref1]`（无定义）、`file:///C:/Users/student/lab02.md`、`[说明](./lab 02.md)`、`http://example.com`，覆盖 `link-001～006`。
  - `demo-repo/lab/uart/uart_demo.c`：无文件头注释、`main` 无紧邻注释、含 `strcpy` 与 `while(1)`、含中文注释，覆盖 `code-001/002/004/007`。
  - `demo-repo/lab/uart/UART Demo-v2.C`：最小 C 文件，用于 `naming-003`。
  - `demo-repo/backend/app/example_config.py`：含 `password = "123456"`、`token = "ghp_abcdef123456"`（无效占位）、无模块 docstring，覆盖 `sens-004/005`、`code-001/002`。
  - `demo-repo/backend/tests/test_demo.py`：最小 `unittest` 用例，带模块 docstring 与函数 docstring，作为 `naming-005` 反例。
  - 不提交任何真实大文件与真实密钥；所有凭据均为无效占位串。

---

## 15. `test_manifest.py` 单元测试

**依赖**：T04（并行组 D）
**目标**：覆盖 spec 5.1.1 第 1～7、10 条与 6.1 数据约束。

### 15.1 测试文件与用例清单

- [ ] 完成 15.1 测试文件与用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_manifest.py`
- **测试框架**：标准库 `unittest`；每个用例独立 `TemporaryDirectory`；表驱动使用 `subTest`。
- **用例清单（覆盖正常、边界、误报规避、降级）**：
  - `test_parse_format`（正常）：`A path`、`A\t path`、多空格、前导空白。
  - `test_lowercase_status`（正常）：`a/m/d` 与大写等价。
  - `test_unknown_status`（降级）：`X notes/a.md`、`1 a.md` → `UnparsedLine`，原因含"未知状态"。
  - `test_missing_path`（降级）：`M`、`M   ` → 原因"缺少文件路径"。
  - `test_ignore_blank_comment`（边界）：空行、仅空白、`#`、前导空白的 `#` → 返回 `None`，不计入任何统计。
  - `test_path_normalize`（正常/边界）：`.\lab\uart\uart_demo.c` → `lab/uart/uart_demo.c`；`a//b` → `a/b`；`././a.md` → `a.md`；中文、大小写、扩展名保留。
  - `test_raw_truncate`（边界）：超过 500 字符的原始行截断为 500。
  - `test_line_no`（正常）：行号从 1 开始，空行/注释行也占行号。
  - `test_duplicate_merge`（正常）：同一路径 A 后 M → 1 条、状态 M、`duplicate_count=2`、`line_no` 首次。
  - `test_merge_order`（正常）：`merge_entries` 保持首次出现顺序。
  - `test_entry_contract`（边界）：空路径、绝对路径、盘符路径的构造/判定行为符合 design 2.3.2（2）。
  - `test_has_escaping_segments`（边界）：`../a.md`、`a/../../b` 返回 True；`a/../b` 归一化后判定一致。
  - `test_no_fs_access_on_invalid`（误报规避）：`unittest.mock.patch("builtins.open")` 与 `os.stat`，解析非法行时断言零调用。
  - `test_load_manifest_text`（正常/降级）：UTF-8、UTF-8 BOM、GB18030 中文均可读；不存在/目录/无权限 → `ManifestReadError` 且消息为中文。
  - `test_crlf`（兼容）：CRLF 与 LF 解析结果一致。

### 15.2 执行与断言要求

- [ ] 完成 15.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_manifest -v` 全部通过。
  - 每个 `rule`/解析分支至少 1 正例 + 1 反例。
  - 不以真实仓库文件为输入，全部使用临时目录或字符串。
  - 断言失败信息为中文说明，便于定位。

---

## 16. `test_naming.py` 单元测试

**依赖**：T06（并行组 D）
**目标**：覆盖 spec 5.2.1 全部 10 条与 5.2.3 三个异常场景。

### 16.1 测试文件与用例清单

- [ ] 完成 16.1 测试文件与用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_naming.py`
- **用例清单**：
  - **正常场景**：
    - `test_illegal_chars`：`lab/a:b.c`、`lab/a*b.c`、`lab/a?.c`、结尾点 → `naming-001`，建议含替换为 `_` 的名称。
    - `test_long_name`：121 字符 → `naming-002`；120 字符不报。
    - `test_style_advice`：`lab/uart/UART Demo-v2.C` → `naming-003`，建议含 `uart_demo_v2.c`。
    - `test_chinese_name_advice_only`：`docs/lab03_串口通信实验.md` → `naming-004`，级别必须为"优化建议"，示例含 `docs/lab03_serial_communication.md`。
    - `test_wrong_directory_must_fix`：`docs/uart_demo.c` → `naming-005`，建议 `lab/uart/uart_demo.c`；`backend/app/a.md` → 建议 `docs/`；`lab/test_x.py` → 建议 `backend/tests/`。
    - `test_root_source_advice`：根目录 `uart_demo.c` → `naming-006`，建议 `lab/<module>/`。
    - `test_directory_map`：`.md`/`.c`/`.h`/`.py`/图片/测试文件映射逐项校验。
  - **边界场景**：
    - `test_no_extension`：`lab/Makefile` 只做非法字符与长度检查，不输出目录问题。
    - `test_unknown_extension`：`lab/a.xyz` 不输出目录问题。
    - `test_merge_style_issues`：大写 + 空格 + 连字符 → 只输出 1 条风格建议。
    - `test_merge_directory_issues`：同时命中 005/006 → 只输出 005。
    - `test_max_four_findings`：每文件最多 4 条。
    - `test_directory_prefix_boundary`：`backendx/a.md` 不误判为 `backend/`。
  - **误报规避**：
    - `test_no_must_fix_for_chinese`：纯中文名 0 条必须修改，最多 1 条建议。
    - `test_pinyin_hyphen_ok`：拼音名、带连字符英文名不得判必须修改。
    - `test_suggestion_has_example`：每条命名/目录问题的 `suggestion` 含具体名称或目标路径，禁止只写"命名不规范"。
  - **降级/零 I/O**：
    - `test_deleted_status_no_read`：`D` 条目调用 `check` 时 `ctx.snapshot` 断言零调用。
    - `test_rule_ids_stable`：产出 `rule_id` 仅限 `naming-001`～`naming-006`。

### 16.2 执行与断言要求

- [ ] 完成 16.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_naming -v` 全部通过。
  - 断言必须同时校验 `level`、`rule_id`、`message` 非空、`suggestion` 含示例。
  - 不读取真实文件，全部以 `ChangeEntry` + 临时 `CheckContext` 构造。

---

## 17. `test_code_scan.py` 单元测试

**依赖**：T07（并行组 D）
**目标**：覆盖 spec 5.3.1 全部 10 条与 5.3.3 四个异常场景。

### 17.1 测试文件与用例清单

- [ ] 完成 17.1 测试文件与用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_code_scan.py`
- **用例清单**：
  - **正常场景**：
    - `test_scope`：`D` 状态、`.md`/`.txt` → 空结果，不创建快照。
    - `test_module_header`：无模块 docstring 的 `.py` → `code-001`；首行 docstring 不报；无文件头注释的 `.c` → `code-001`。
    - `test_public_function_comment`：无注释 `main` → `code-002`；Python 公开函数缺 docstring → `code-002`；类方法缺 docstring → `code-002`。
    - `test_static_helper_advice`：8 行 `static` 无注释 → `code-003`（优化建议）；有 `//` 注释不报。
    - `test_high_risk`：`strcpy`/`gets`/`strcat`/`sprintf`/`scanf("%s")` → `code-004`（必须修改）；`eval(user_input)`/`exec(code)` → `code-005`；`os.system("rm " + name)` → `code-006`。
    - `test_suspicious`：`while(1)`、`for(;;)`、`os.system(`、`subprocess`、裸 `except:`、魔法数字 → `code-007`（优化建议）。
    - `test_line_number`：第 27 行 `strcpy` → `line_no=27`。
    - `test_chinese_comment_ok`：中文注释视为满足，不报 `code-002`。
  - **边界场景**：
    - `test_comment_position`：函数体内注释不算函数注释；定义前允许间隔空行；docstring 必须在函数体第一处语句。
    - `test_header_with_bom_and_blank`：BOM + 前导空行后仍有注释 → 不报 `code-001`。
    - `test_aggregation`：同规则 6 处 → 5 条 + 1 条"另有 N 处同类问题"。
  - **误报规避**：
    - `test_comment_string_no_false_positive`：注释、docstring、普通字符串中的 `strcpy`/`eval` 不报。
    - `test_literal_eval_ok`：`ast.literal_eval(text)`、`model.eval()` 不报 `code-005`。
    - `test_subprocess_list_ok`：`subprocess.run(["ls"])` 不报 `code-006`。
    - `test_syntax_error`：`ast.parse` 失败 → 不产生注释误报，仅保留文本匹配结果。
    - `test_macro_wrapped_skip`：宏包裹/无法确定边界的函数片段跳过，不误报。
    - `test_no_style_must_fix`：缩进宽度、行长、命名大小写不得产生必须修改。
  - **降级/跳过**：
    - `test_header_downgrade`：`.h` 的全部结果降为优化建议。
    - `test_large_file_skip`：> 5 MB → `code-008`，不报注释类问题。
    - `test_binary_or_encoding_skip`：二进制/编码失败 → `skip_reason="文件内容无法解码，已跳过代码检查"`。
    - `test_no_execution`：被扫描 `.py` 内含 `raise RuntimeError` 与写文件语句，断言未执行、无副作用。

### 17.2 执行与断言要求

- [ ] 完成 17.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_code_scan -v` 全部通过。
  - 每条高危/可疑断言必须校验 `line_no` 与 `excerpt`（允许 `None`，但行号不得缺失）。
  - 大文件用例使用临时目录生成占位内容，不提交大文件。
  - `.h` 用例断言不存在"必须修改"级别。

---

## 18. `test_link_check.py` 单元测试

**依赖**：T08（并行组 D）
**目标**：覆盖 spec 5.4.1 全部 11 条与 5.4.3 四个异常场景。

### 18.1 测试文件与用例清单

- [ ] 完成 18.1 测试文件与用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_link_check.py`
- **用例清单**：
  - **正常场景**：
    - `test_scope`：`D` 状态、非 `.md` → 空结果。
    - `test_extract_types`：行内、图片、引用式、定义式、裸链接各 1 例，`kind` 正确。
    - `test_empty_target`：`[说明]()` → `link-001`（必须修改）。
    - `test_unclosed`：`[说明](./lab03.md` → `link-002`，描述含缺失右括号位置。
    - `test_missing_definition`：`[说明][ref1]` 无定义 → `link-003`；有 `[ref1]: ./a.md` 不报。
    - `test_absolute_path`：`file:///C:/Users/student/lab03.md` → `link-004`（优化建议）。
    - `test_space_in_target`：`[说明](./lab 03.md)` → `link-005`（必须修改）；`[说明](<./lab 03.md>)` 不报。
    - `test_protocol_advice`：`http://example.com`、`localhost`、内网 IP、`[](./a.md)` → `link-006`。
    - `test_line_and_excerpt`：第 12 行畸形链接 → `line_no=12`，`excerpt` ≤ 60 字符。
  - **边界场景**：
    - `test_chinese_anchor_ok`：`./实验指导.md#第三部分` 不产生必须修改，最多 1 条优化建议。
    - `test_reference_defined_later`：定义在文末仍能识别。
    - `test_many_links`：201 条 → `link-008`；200 条不报。
    - `test_multiline_link`：结构不成立的跨行链接报 `link-002`；合法续行不报。
    - `test_same_line_dedup`：同一行同一链接只报最高级别 1 条。
    - `test_rule_aggregation`：同规则超过 5 条 → 合并为"另有 N 处同类问题"。
  - **误报规避**：
    - `test_skip_code_block`：``` 与 ~~~ 围栏内链接不报；行内反引号代码不报；围栏长度规则正确。
    - `test_shortcut_reference_no_false_positive`：`[标识]` 无定义时不按引用式报错。
    - `test_no_network`：`patch("socket.socket", side_effect=AssertionError)` 执行检查，断言无网络调用。
  - **降级**：
    - `test_outside_repo`：`../outside.md` → `link-007` 优化建议，不读取目标。
    - `test_binary_or_encoding_skip`：编码失败 → `skip_reason="Markdown 内容无法解码，已跳过链接检查"`。
    - `test_no_links`：无链接文档 → 空结果，无链接类条目。

### 18.2 执行与断言要求

- [ ] 完成 18.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_link_check -v` 全部通过。
  - 每条校验断言 `line_no` 非空、`excerpt` 长度 ≤ 60。
  - 测试不访问文件系统目标路径，全部使用字符串输入。
  - `link-001/002/003/005` 断言级别为"必须修改"；`link-004/006/007/008` 断言为"优化建议"。

---

## 19. `test_sensitive.py` 单元测试

**依赖**：T09（并行组 D）
**目标**：覆盖 spec 5.5.1 全部 10 条与 5.5.3 四个异常场景，重点验证脱敏。

### 19.1 测试文件与用例清单

- [ ] 完成 19.1 测试文件与用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_sensitive.py`
- **用例清单**：
  - **正常场景**：
    - `test_warn_size`：2 MB → `sens-001`（优化建议）；900 KB 不报。
    - `test_fail_size`：6 MB → `sens-002`（必须修改）；4 MB 不报 002。
    - `test_binary_size_only`：12 MB 的 `.mp4` → 仅 `sens-002`，无内容类问题；NUL 字节兜底同样跳过文本扫描。
    - `test_private_key_token`：`BEGIN RSA PRIVATE KEY` → `sens-003`；`ghp_abcdef123456` → `sens-004`；AWS AK、`github_pat_`、`glpat-`、`xoxb-`、`sk-`、`AIza` 各 1 例。
    - `test_password_conn`：`password = "123456"` → `sens-005`；`mysql://user:pass@host/db` → `sens-005`。
    - `test_entropy_advice`：40 位 hex → `sens-006`（优化建议）；8 位普通字符串不报。
    - `test_mask`：`ghp_abcdef123456` → `ghp_****`；长度 ≤ 4 → `****`；`message`/`suggestion`/`excerpt` 均不含原文。
  - **边界场景**：
    - `test_size_boundary`：恰好 1 MB、恰好 5 MB 的判定口径。
    - `test_empty_file`：0 字节/仅空白 → 无体积与内容问题。
    - `test_aggregation`：同文件 5 处 `sens-004` → 1 条，列出前 3 个行号 + "共 N 处"。
    - `test_placeholder_exemption`：`示例占位 token = "ghp_..."` → `sens-004` 降为优化建议；PEM 即使带"示例"仍为必须修改。
    - `test_placeholder_exclusions`：`password = os.getenv("PWD")`、`${VAR}`、`<...>`、`{{...}}`、`your_`、"请输入"不报 `sens-005`。
  - **误报规避**：
    - `test_binary_no_text_match`：二进制内容中的 `password=` 不报内容问题。
    - `test_no_high_entropy_duplicate`：同时命中 `sens-004`/`sens-006` 只保留必须修改项，不重复报建议。
    - `test_no_network_no_write`：`patch("socket.socket", side_effect=AssertionError)`，并断言临时目录文件列表与内容前后一致。
  - **降级/跳过**：
    - `test_deleted_skip`：`D` 状态不 `stat`、不报体积与内容问题。
    - `test_missing_file_skip`：文件不存在 → `skip_reason="无法获取文件信息，已跳过"`。
    - `test_timeout`：构造超预算场景 → `sens-007`（优化建议），保留体积结论。
    - `test_no_real_credentials`：样例与测试数据中的凭据必须为无效占位串。

### 19.2 执行与断言要求

- [ ] 完成 19.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_sensitive -v` 全部通过。
  - 每个脱敏用例必须额外断言：报告全文不含完整原文（用 `assertNotIn`）。
  - 体积用例通过临时文件按字节写入生成，不提交大文件。
  - `sens-003`/`sens-004`/`sens-005` 断言"必须修改"；`sens-001`/`sens-006`/`sens-007` 断言"优化建议"。

---

## 20. `test_engine.py` 集成测试

**依赖**：T11、T13、T15、T16、T17、T18、T19
**目标**：覆盖 spec 5.6.1 全部 11 条、5.1.3/5.6.3 异常场景、四模块协同与 design 2.4.4 导入方向。

### 20.1 契约、分组与排序

- [ ] 完成 20.1 契约、分组与排序

- **创建文件（完整相对路径）**：`backend/tests/test_engine.py`
- **用例清单**：
  - `test_single_entry`：一次调用返回四类完整结果。
  - `test_group_by_file`：同一文件两条问题只出现一个分组；无问题文件保留分组。
  - `test_finding_contract`：四必填字段非空；`level` 仅两个中文值；`rule_id` 存在且格式为 `前缀-三位序号`。
  - `test_report_contract`：`status`/`summary`/`files`/`unparsed_lines`/`degraded_modules`/`warnings` 六项齐全。
  - `test_summary_counts`：3 条问题（1 必须 + 2 建议）→ 统计完全一致；7 项统计与 design 2.3.2（4）不变量成立。
  - `test_sort_order`：文件按 Unicode 码点排序；文件内"必须修改"先于"优化建议"；同级按行号升序；无行号排末尾。
  - `test_empty_report`：空清单 → 全零统计、`files=()`、warning 含"变更清单为空"。
  - `test_text_summary`：摘要开头有必须修改数量与"先处理必须修改项"引导语。
  - `test_json_utf8`：`report_to_json` 中文不转义、无 `\uXXXX`。
  - `test_empty_manifest_string`：`""`、全空白、仅注释 → 空报告。

### 20.2 异常、只读、离线与确定性

- [ ] 完成 20.2 异常、只读、离线与确定性

- **修改文件（完整相对路径）**：`backend/tests/test_engine.py`
- **用例清单**：
  - `test_input_error_repo_root`：仓库根不存在/非目录 → `输入错误`、统计全零、退出码语义 2。
  - `test_manifest_unreadable`：清单文件不存在 → `输入错误` + 中文 warning，不抛异常。
  - `test_degrade_visible`：注入某模块异常 → `degraded_modules` 非空、`status=部分降级`、摘要含"结果可能不完整"。
  - `test_deleted_status_no_read`：D 状态不创建快照、不报内容问题，命名结果保留。
  - `test_read_only`：执行前后对被测文件计算 `size + sha256 + mtime`，断言完全一致；目录文件列表不变。
  - `test_no_network`：`patch("socket.socket", side_effect=AssertionError)` 包裹 `run_check`。
  - `test_no_code_execution`：被扫描 `.py` 内含 `raise`/写文件语句，断言副作用未发生。
  - `test_path_escape`：`../outside.md`、`C:\Windows\win.ini`、`//server/share/a.md`、指向仓库外的符号链接 → 宿主分组 `skip_reason` 含"路径超出仓库范围"。
  - `test_encoding_compat`：UTF-8 BOM、GB18030 中文、非法字节、CRLF → BOM/GB18030 正常，非法字节跳过并提示。
  - `test_path_separator_consistent`：`lab\uart\uart_demo.c` 与 `lab/uart/uart_demo.c` 输出一致且统一 `/`。
  - `test_report_is_deterministic`：同输入连续两次 `report_to_json()` 字符串完全相等。
  - `test_all_skipped`：全部条目被跳过 → 空问题列表 + 跳过统计 + 指定提示文案。
  - `test_partial_degraded_status`：无必须修改但有模块降级 → `部分降级`，退出码语义 3。

### 20.3 交付物、导入方向与性能

- [ ] 完成 20.3 交付物、导入方向与性能

- **修改文件（完整相对路径）**：`backend/tests/test_engine.py`
- **用例清单**：
  - `test_delivery_files_exist`：五个业务文件同时存在且可导入。
  - `test_requirements_txt`：解析非注释行，断言为空。
  - `test_sample_manifest_covers_all_modules`：以 `demo-repo` 为根运行样例清单，断言 `naming-`/`code-`/`link-`/`sens-` 四类前缀均出现。
  - `test_import_direction`：使用标准库 `ast` 扫描 `backend/app/` 下全部产品 `.py` 的 `Import`/`ImportFrom` 节点，断言不存在：`common → engine/检查模块`、检查模块 → `engine`、检查模块横向互导、`engine → app.core.rules` 包根、任何对 `app.api/app.db/app.models/app.services` 的导入、任何第三方包导入。
  - `test_performance_500`：生成 500 条清单、100 个可读文件，断言端到端 < 10 s（CI 可放宽 2 倍）；仅在环境变量 `RULES_PERF=1` 时执行，默认 `skip`。
- **验收标准**：
  - `cd backend && python -m unittest tests.test_engine -v` 全部通过（性能用例默认跳过）。
  - `RULES_PERF=1 python -m unittest tests.test_engine.EnginePerformanceTest -v` 通过性能基线。
  - 集成用例使用临时目录工厂构造数据，不依赖开发者手工准备文件。
  - 断言失败信息为中文。

---

## 21. `test_cli.py` 命令行测试

**依赖**：T12、T20
**目标**：覆盖 spec 5.6.1 第 8 条、6.4 配置回退与 7.1 交付验收。

### 21.1 命令行用例清单

- [ ] 完成 21.1 命令行用例清单

- **创建文件（完整相对路径）**：`backend/tests/test_cli.py`
- **用例清单**：
  - `test_exit_codes`：0（仅建议/空）、1（必须修改）、2（仓库根不存在/清单不可读）、3（模块降级/序列化回退）。
  - `test_format_text`：默认 `text` 输出中文摘要。
  - `test_format_json`：`--format json` 输出可解析 JSON，中文不转义。
  - `test_output`：`--output` 指定路径时写 JSON；未指定时仓库内不产生任何文件。
  - `test_stdin_manifest`：`--manifest -` 从 stdin 读取。
  - `test_default_repo`：省略 `--repo` 时默认 `"."`。
  - `test_config_fallback`：非法 JSON、阈值倒置、未知字段、`directory_map` 缺项 → 回退默认 + 中文 warnings，退出码不受影响。
  - `test_config_override`：合法配置覆盖阈值生效。
  - `test_debug_no_secret`：`--debug` 输出不包含完整凭据、私钥、密码原文。
  - `test_no_stack_trace`：正常模式 stdout/stderr 不含 `Traceback`、英文异常类名。
  - `test_output_unwritable`：`--output` 指向不可写路径 → 保留 stdout，warning"无法写入输出文件"，退出码 3。
  - `test_help`：`--help` 退出 0 并列出全部参数。

### 21.2 执行与断言要求

- [ ] 完成 21.2 执行与断言要求

- **验收标准**：
  - `cd backend && python -m unittest tests.test_cli -v` 全部通过。
  - CLI 测试通过 `main(argv)` 直接调用，必要时用 `unittest.mock.patch("sys.stdout")` 捕获输出。
  - 断言使用 `ExitCode` 枚举值，不硬编码魔法数字。
  - 所有临时文件位于 `TemporaryDirectory`，结束后自动清理。

---

## 22. 端到端验收（样例清单 → engine → 分组报告 + 退出码）

**依赖**：T14、T21
**目标**：在真实样例仓库上完成一次完整链路验证，作为交付验收证据。

### 22.1 端到端执行

- [ ] 完成 22.1 端到端执行

- **涉及路径**：
  - 输入：`backend/tests/fixtures/sample_changes.txt`、`demo-repo/`
  - 入口：`backend/app/core/rules/engine.py`
  - 输出：stdout（不写入仓库）
- **执行命令（固定）**：
```text
cd backend
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo --format json
```
- **验收标准**：
  - 两条命令退出码均为 1（样例中存在必须修改项），且不抛出英文堆栈。
  - text 输出包含"RepoGuard 规则检查结果"、必须修改/优化建议数量、"请先处理「必须修改」项"。
  - json 输出可被 `json.loads` 解析，`status` 为"正常"或"部分降级"，`summary` 七项齐全。
  - 报告按文件分组，每个路径只出现一次；同一文件内必须修改在优化建议之前。
  - 不产生任何仓库内新文件（除 `--output` 显式指定外）。

### 22.2 分组报告与统计断言

- [ ] 完成 22.2 分组报告与统计断言

- **验收标准**：
  - `lab/uart/uart_demo.c` 分组：状态 `M`、`duplicate_count=2`，含 `code-` 与 `sens-` 前缀问题。
  - `docs/lab03_串口通信实验.md` 分组：仅 `naming-004` 优化建议，无必须修改。
  - `docs/uart_demo.c` 分组：含 `naming-005`（必须修改），建议目标 `lab/uart/uart_demo.c`。
  - `docs/lab02_broken_link.md` 分组：含 `link-001`～`link-006` 中至少 4 类，全部带行号。
  - `backend/app/example_config.py` 分组：含 `sens-004`/`sens-005` 必须修改，且输出中不出现 `ghp_abcdef123456` 与 `123456` 原文（仅 `ghp_****` 等脱敏形式）。
  - `notes/old_lab02.md` 分组：状态 `D`，仅有命名类结果或为空，不含体积/内容问题。
  - `unparsed_lines` 恰好 2 条：`X notes/unknown_status.md`（未知状态）、`M`（缺少文件路径）。
  - `entry_count` 等于合并后的有效条目数（样例为 9），`issue_count == must_fix_count + suggestion_count`。
  - 四个 `rule_id` 前缀 `naming-`/`code-`/`link-`/`sens-` 均出现（spec 7.1 第 3 条）。
  - 连续执行两次，text/json 输出逐字节一致（spec 7.1 第 4 条）。
  - 大文件条目 `assets/large_sample.mp4` 未放置时显示"文件不存在，已跳过内容检查"，不影响其余模块输出。
  - 若本地临时生成 > 5 MB 占位文件，则出现 `sens-002`（必须修改）且退出码仍为 1。

---

## 23. 依赖清单 `backend/requirements.txt`

**依赖**：T01（并行组 A）
**目标**：满足 spec 7 第 6 条与 7.1 第 2 条"零第三方依赖"。

### 23.1 文件内容与验收

- [ ] 完成 23.1 文件内容与验收

- **创建文件（完整相对路径）**：`backend/requirements.txt`
- **内容要求**：
  - 第 1 行：`# RepoGuard 规则引擎运行依赖`
  - 第 2 行：`# Python >= 3.10（仅使用标准库，无第三方包）`
  - 其余行：无；文件末尾保留一个换行。
- **验收标准**：
  - 非注释行（去除空白后）为空，解析器读取结果为空列表。
  - 不出现 `pytest`、`markdown`、`pyyaml`、`requests` 等开发/可选依赖。
  - 不写版本锁定、不作 hash 锁定。
  - UTF-8 无 BOM。
  - 与 `test_engine.test_requirements_txt` 的断言一致。

---

## 24. 中文使用说明 `docs/rules_engine_usage.md`

**依赖**：T22
**目标**：满足 spec 7 第 8 条，面向学生新人可照做。

### 24.1 文档结构与内容

- [ ] 完成 24.1 文档结构与内容

- **创建文件（完整相对路径）**：`docs/rules_engine_usage.md`
- **必须包含的章节**：
  1. **规则引擎能做什么**：四项检查、两类问题级别、面向学生的引导定位。
  2. **如何生成变更清单**：每行"状态 + 空格 + 路径"，A/M/D 含义，小写等价，空行与 `#` 注释行规则，`\` 与 `/` 均可，路径必须位于仓库内；给出手工整理与脚本生成的示例命令（不要求引擎执行 Git）。
  3. **如何调用汇总入口**：Python 进程内调用与命令行调用各 1 例，工作目录固定 `backend/`，参数表（`--manifest`/`--repo`/`--format`/`--output`/`--config`/`--debug`）。
  4. **如何阅读报告**：按文件分组、必须修改优先、"问题描述 + 修改建议"字段说明、跳过文件与降级模块的含义。
  5. **退出码说明**：0/1/2/3 的语义与优先级 `2 > 3 > 1 > 0`。
  6. **配置说明**：阈值、目录映射、特征清单的可配置项；固定不可配置项（中文名只建议、私钥/真实令牌必须修改、只读离线、中文输出、脱敏策略）。
  7. **样例运行**：给出 `cd backend` 后运行 `sample_changes.txt` 与 `demo-repo` 的命令，说明大文件样例默认不提交及本地生成方式。
  8. **常见问题**：文件编码、路径越界、模块降级、中文终端显示。
- **验收标准**：
  - 全文简体中文，命令与字段名保留英文原文。
  - 文档中的命令可直接复制执行，路径与实际交付结构一致。
  - 明确"本工具不自动修复、不执行 Git、不联网、不编译被扫描代码"。
  - 不包含真实密钥；示例凭据为无效占位串。
  - 文档不承诺未实现能力（不做链接可达性检测、不做全量静态分析）。

### 24.2 文档校验

- [ ] 完成 24.2 文档校验

- **验收标准**：
  - 按文档命令在 `backend/` 下实际执行 1 次，输出与文档描述一致。
  - 文档中出现的全部文件路径均真实存在（除说明为可选的 `large_sample.mp4`）。
  - 章节编号连续、无 TODO 占位。

---

## 25. 全量回归与交付验收

**依赖**：T22、T23、T24
**目标**：一次性核对 spec 7.1 四条验收条件与 design 2.12.3 完成标准。

### 25.1 全量测试执行

- [ ] 完成 25.1 全量测试执行

- **验收标准**：
  - 在 `backend/` 下执行 `python -m unittest discover -s tests -v`，全部用例通过、无 skipped（性能用例按开关除外）。
  - 依次单独执行 `test_manifest`、`test_naming`、`test_code_scan`、`test_link_check`、`test_sensitive`、`test_engine`、`test_cli`，均通过。
  - `RULES_PERF=1` 性能用例通过或记录明确偏差与原因。
  - 测试执行后仓库内不新增任何文件（`git status` 等价检查，当前非 Git 仓库时用目录快照比对）。

### 25.2 交付清单核对

- [ ] 完成 25.2 交付清单核对

- **验收标准逐条核对（spec 7.1）**：
  1. `backend/app/core/rules/` 下同时存在 `naming.py`、`code_scan.py`、`link_check.py`、`sensitive.py`、`engine.py` 五个文件。
  2. `backend/requirements.txt` 非注释行为空。
  3. `sample_changes.txt` 运行后 `naming-`/`code-`/`link-`/`sens-` 四类前缀均出现。
  4. 样例清单连续两次执行，问题集合与统计数值完全一致。
- **路径合规核对（design 2.4.3（1））**：
  - 产品源码 14 个 `.py` 全部位于 `backend/app/`。
  - 测试资产 7 个 `backend/tests/test_*.py` 存在。
  - `demo-repo/**` 下的 `.py` 仅作为被扫描样例，不被产品代码导入。
  - 仓库根、`scripts/`、`frontend/` 下不存在产品 `.py`。
- **导入方向核对**：`test_engine.test_import_direction` 通过；人工抽查 `common/**` 无反向导入。
- **职责边界核对**：无自动修复、无 Git 命令、无网络导入、无代码执行、无 Web 页面、无默认写文件。
- **文档核对**：`docs/rules_engine_usage.md` 存在且按 T24 章节结构完成。

### 25.3 遗留问题与交付说明

- [ ] 完成 25.3 遗留问题与交付说明

- **验收标准**：
  - 记录未能覆盖的规则或环境限制（如 Python 解释器异常、C 宏包裹无法识别、`.svg` 默认按二进制处理），每条附原因与影响范围。
  - 记录性能实测值（500 条 / 100 文件端到端耗时、单文件耗时、5 MB 文本扫描耗时）。
  - 确认新增/修改文件清单与 design 2.10.1 一致，无越界文件（不修改 `frontend/`、`app/api/`、`app/db/`、`app/models/`、`app/services/`）。
  - 输出一份中文交付说明，供后续阶段直接接手。
  - 本任务完成后停止，不进入任何代码实现或部署动作（由后续实现阶段执行）。
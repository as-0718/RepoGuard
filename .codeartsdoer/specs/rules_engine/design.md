# 一、需求与存量功能关系分析

> 分析依据：`.codeartsdoer/specs/rules_engine/spec.md`（666 行，唯一需求来源）、对仓库根目录的实际扫描结果（2026-11-05）。
> 扫描结论：`backend/app/core/rules/`、`backend/tests/`、`frontend/`、`docs/`、`scripts/`、`demo-repo/{docs,lab,notes}` 均为空目录；全仓库无 `.py`、无配置文件、无 `requirements.txt`、无构建脚本，且当前目录不是 Git 仓库。因此本次是 **全新实现（greenfield）**，不存在可直接复用的业务逻辑。

## 1.1 需求功能与存量功能对比

### 1.1.1 已实现功能

**判定说明**：本仓库无任何业务代码，四项检查、清单解析、汇总报告、CLI 均**没有**实现，不存在 100%/75% 匹配项。下表仅列出"交付路径占位"这一项可复用的存量资产，匹配度按"物理位置就绪、逻辑为零"记为 25%，避免将空目录误判为已实现功能。

| 需求功能 | 存量功能 | 代码位置 | 匹配度 |
|---------|---------|---------|--------|
| 五个规则文件的交付路径 | 空目录 `backend/app/core/rules/` 已存在，可直接落盘，无需创建父目录 | `backend/app/core/rules/`（空目录） | 25%（路径占位，业务逻辑 0%） |
| 测试与样例清单的交付路径 | 空目录 `backend/tests/` 已存在，可容纳 `fixtures/sample_changes.txt` 与测试文件 | `backend/tests/`（空目录） | 25%（路径占位，无测试代码） |
| 端到端样例仓库 | `demo-repo/` 下已有 `docs/`、`lab/`、`notes/` 三个空目录，可作为样例清单的仓库根骨架 | `demo-repo/`（空目录树） | 25%（目录骨架可复用，无样例文件） |

**结论**：spec 5.1～5.6 描述的全部业务能力均为 0% 存量覆盖，必须在本阶段新增。

### 1.1.2 需要扩展的功能

**判定说明**：严格意义上没有"已有实现等待改造"的功能。以下三项属于"空目录 → 可运行包"的工程化补齐，归入扩展类而非新增业务功能，因为落盘位置、目录层级已被仓库骨架约束。

| 需求功能 | 存量功能 | 差异说明 | 扩展方向 |
|---------|---------|---------|---------|
| 可导入的 Python 包结构 | 仅有空目录 `backend/app/<br>backend/app/core/<br>backend/app/core/rules/`，无 `__init__.py` | 空目录无法被 `import`，`python -m` 无法解析包路径 | 补充 `app/__init__.py`、`app/core/__init__.py`、`app/core/rules/__init__.py`；运行工作目录固定为 `backend/`，包名 `app.core.rules`；不引入 `pyproject.toml`/打包发布，避免与学生本地环境耦合 |
| 运行入口 | 无任何可执行脚本，`scripts/` 为空 | 缺少参数解析、退出码、stdout 渲染 | 在 `engine.py` 内提供 `main(argv) -> int` 与 `if __name__ == "__main__"` 守卫，支持 `python -m app.core.rules.engine`；不新增顶层 `cli.py`，以便 `rules/` 顶层只保留五个业务文件 |
| 样例仓库与样例清单 | `demo-repo/docs`、`demo-repo/lab`、`demo-repo/notes` 为空；`backend/tests/` 无 fixtures | 样例清单需要真实文件才能触发四类检查 | 在 `demo-repo/` 下补充最小样例文件（含缺注释 `.c`、异常链接 `.md`、中文名文档、大文件、疑似密钥），并以 `demo-repo/` 为 `--repo` 运行 `sample_changes.txt`；测试另用临时目录工厂构造可控数据，避免测试相互污染 |

### 1.1.3 需要新增的功能或接口

**判定说明**：按"能力组"分组列出。每组均无存量实现，依赖关系仅指向本组件内部新增单元与 Python 标准库；禁止依赖 `app.api`、`app.db`、`app.models`、`app.services`（这些目录同样为空，且规则引擎不得反向依赖 Web 层）。

#### A. 输入与文件访问层（对应 spec 5.1、4.2、4.3、4.5）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 变更清单文本解析 | UTF-8 文本（字符串或清单文件） | `ChangeEntry` 列表 + `UnparsedLine` 列表 | 逐行去除行尾 CR/LF；跳过空白行与 `#` 注释行；首字符为 A/M/D（大小写不敏感）且后随空白 → 余下内容为路径；其他 → 记非法行并附行号与原因 | 标准库 `re` |
| 路径归一化 | 原始路径字符串 | 以 `/` 分隔的相对路径 | 去除首尾空白、循环去除 `./` 前缀、`\`→`/`、折叠重复分隔符、消除 `.` 段；保留中文、大小写、扩展名 | 无 |
| 路径沙箱校验 | 归一化路径 + 仓库根绝对路径 | 合法/非法判定 | 拒绝绝对路径（`/`、盘符、UNC）；拒绝解析后 `realpath` 不位于仓库根内（`commonpath` 比较，Windows 用 `casefold`）；拒绝符号链接逃逸；非法路径不触发任何 `stat`/`open` | `os.path`、`pathlib` |
| 重复路径合并 | `ChangeEntry` 列表 | 去重后的条目 | 以归一化路径为键；状态取最后一次出现；`duplicate_count` 累加；行号保留首次出现行号 | 无 |
| 文件快照（单次读取） | 合法路径 | `FileSnapshot`（体积、二进制标志、惰性文本） | 首次 `stat` 缓存体积；首次 `text()` 才读取内容并缓存；UTF-8（去 BOM）失败回退 GB18030；二进制按扩展名 + 首 8 KB 含 NUL 判定，不读全文 | `pathlib`、`codecs` |
| 只读与离线保障 | — | — | 仅使用 `r`/`rb` 模式；不调用任何网络库；不写仓库任何位置 | 无 |

#### B. 命名与目录检查（对应 spec 5.2）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 文件名硬规则检查 | 路径 | `Finding`（必须修改） | 非法字符 `< > : " \| ? *`、控制字符、结尾点 → 必须修改并给出替换后名称；长度 > 120 → 必须修改并建议 ≤ 60 | 标准库 `re`、`unicodedata` |
| 命名风格检查 | 路径 | `Finding`（优化建议） | 大写、空格、连字符、连续下划线、非 ASCII → 合并为一条，推荐 lower_snake | 标准库 `re` |
| 中文命名引导 | 路径 | `Finding`（优化建议，最多一条） | 中文只给建议（英文/拼音 + 下划线），说明跨平台工具链不便；**禁止**升级为必须修改 | 标准库 `re` |
| 目录归属硬检查 | 扩展名 + 路径前缀 | `Finding`（必须修改） | `.c/.h` 在 `docs/`；`.md` 在 `backend/`/`src/`/`lab/`；测试文件不在 `backend/tests/` | 配置 `directory_map` |
| 目录归属建议 | 扩展名 + 路径前缀 | `Finding`（优化建议） | 源码在根目录；图片不在 `assets/`/`docs/assets/`；实验报告类 `.md` 不在 `docs/` | 配置 `directory_map` |
| 同类问题收敛 | 全部命名判定 | 最多 4 条/文件 | 命名风格类合并为 1 条，目录类合并为 1 条；非法字符、超长各最多 1 条 | 内部聚合 |

#### C. 代码检查（对应 spec 5.3）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 代码视图构建 | `.py`/`.c`/`.h` 文本 | 去除注释与字符串后的文本 + 行号映射 | 状态机扫描行注释、块注释、单双引号、Python 三引号；仅用于高危写法匹配，避免注释/字符串误报 | 标准库 `re` |
| Python 函数与 docstring 识别 | Python 文本 | 函数列表（名称、起始行、是否公开、行数、是否有紧邻注释） | 使用 `ast` 解析；公开（不以 `_` 开头、含类方法）→ 缺注释必须修改；内部且 ≤ 10 行 → 优化；模块级 docstring 缺失 → 优化 | 标准库 `ast` |
| C 函数识别 | C 文本 | 函数列表（名称、起始行、是否 static、行数、是否有紧邻注释） | 正则识别"返回类型 + 名称 + 参数 + `{`"，排除 `if/for/while/switch/struct/union/enum` 与宏定义；定义前向上跳过空行寻找注释块 | 标准库 `re` |
| 高危写法检查 | 代码视图 + 行号映射 | `Finding`（必须修改，带行号） | `gets`/`strcpy`/`strcat`/`sprintf`/`scanf("%s")`；Python `eval(`/`exec(`；字符串拼接执行 shell；给出 `snprintf`/`fgets`/`shlex` 等替代写法 | 配置 `hard_dangerous_patterns` |
| 可疑写法检查 | 代码视图 + 行号映射 | `Finding`（优化建议） | `while(1)`/`for(;;)`、`os.system`、`subprocess`、裸 `except:`、重复魔法数字；说明适用场景 | 配置 `suspicious_patterns` |
| `.h` 级别降级 | `.h` 的判定结果 | 全部降为优化建议 | 按 spec 5.3 开头约定，`.h` 同族规则但结果只允许优化建议 | 内部级别裁剪 |
| 代码问题聚合 | 每文件每规则 | 最多 5 条 + 1 条汇总 | 超出部分合并为"另有 N 处同类问题"，防止报告膨胀 | 内部聚合 |

#### D. 链接检查（对应 spec 5.4）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 代码块剔除 | Markdown 文本 | 可检查文本（保留行号） | 识别 ``` / ~~~ 围栏（含 info string 与长度 ≥ 开启的闭合），块内不检查；剔除行内 `` ` `` 代码片段 | 标准库 `re` |
| 链接提取 | 可检查文本 | 链接记录（行号、原文、目标、类型） | 行内 `[文本](目标)`、图片 `![说明](目标)`、引用式 `[文本][标识]`/`[标识][]`、定义 `[标识]: 目标`、裸 `http(s)://` | 标准库 `re` |
| 结构合法性检查 | 链接记录 | `Finding`（必须修改） | 空目标；`]`/`)` 缺失或括号错乱；引用标识无定义；目标含未用 `<>` 包裹的空格 | 内部括号配对扫描 |
| 协作适配检查 | 链接记录 | `Finding`（优化建议） | 盘符/`file:///`/本机用户目录；`http://`；`localhost`/内网 IP；空链接文本；中文未编码；`../` 越出仓库 | 配置 + `ipaddress` 标准库 |
| 大批量链接聚合 | 链接总数 | 1 条说明性优化建议 | 单文件 > 200 条链接时输出"共 N 条链接、M 条存在格式问题"，同文件同类问题聚合 | 内部统计 |

#### E. 敏感信息与大文件检查（对应 spec 5.5）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 体积分级 | 文件体积 | `Finding` | > 5 MB 必须修改；> 1 MB 且 ≤ 5 MB 优化建议；D 状态不检查 | `stat` |
| 二进制识别与跳过内容扫描 | 扩展名 + 首 8 KB | 二进制标志 | 图片/音视频/压缩包/可执行文件按扩展名判定，另以 NUL 字节兜底；二进制只报体积 | 无 |
| 凭据特征匹配 | 文本行 | `Finding`（必须/优化） | PEM 私钥头、云厂商 AK、GitHub/平台令牌、明文密码/密钥字段、带账号密码连接串、≥32 位高熵串/长 hex、空值占位 | 配置 `secret_patterns` |
| 教学示例豁免 | 匹配行 + 上下文 | 级别降级 | 前后 80 字符含"示例/占位/demo/example/xxxx"→ 降为优化建议；PEM 与已知真实令牌**不豁免** | 配置 `placeholder_context_words` |
| 脱敏 | 敏感原文 | 前 4 字符 + `****` | 长度 ≤ 4 时整体掩码；描述、建议、`excerpt` 全部脱敏；不写日志 | 无 |
| 凭据问题聚合 | 命中的行号列表 | 1 条/文件 | 列出前 3 个行号，其余显示"共 N 处" | 内部聚合 |
| 内容扫描限时 | 大文本 | 部分结果 + 跳过说明 | 按 64 KB 分块读取，每块检查 1 s 预算；超时保留体积结论并提示"仅完成体积检查" | `time.perf_counter` |

#### F. 汇总入口与报告（对应 spec 5.6）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 唯一公共入口 | 清单文本/清单路径 + 仓库根 + 配置 | `CheckReport` | 串联解析、合并、四模块调度、汇总、统计，调用方无需自行调用模块 | A～E 全部 |
| 模块隔离调度 | 文件条目 | 合并后的 `Finding` 列表 + 降级列表 | 每模块 `try/except Exception`；模块异常 → 记降级并继续其余模块；单文件异常 → 记跳过，不降级模块 | 无 |
| 按文件分组 | `Finding` + `ChangeEntry` | `FileGroup` 列表 | 以路径分组；携带状态、问题、跳过原因、重复次数；每文件只出现一次 | 无 |
| 稳定排序 | 分组与问题 | 排序后的结构 | 文件按 Unicode 码点升序；问题"必须修改 → 优化建议"，同级按 `line_no` 升序，无行号排末尾，再按 `rule_id`、`message` 兜底 | 无 |
| 统计与状态 | 全量结果 | `CheckSummary` + `ReportStatus` | 七项统计（含无法解析行）；状态取"正常/部分降级/输入错误" | 无 |
| 中文摘要渲染 | `CheckReport` | 终端文本 | 开头列必须修改数量并引导学生"先处理必须修改项"；按文件分组；附跳过与降级说明；固定中文 | 无 |
| JSON 序列化 | `CheckReport` | UTF-8 JSON 字符串 | `ensure_ascii=False`，中文不转义；不可序列化时回退到四必填字段最小结构并记降级 | 标准库 `json`、`dataclasses` |
| 命令行入口与退出码 | argv | 退出码 | `--manifest`、`--repo`、`--format text\|json`、`--config`、`--output`；退出码 0/1/2/3 | 标准库 `argparse` |

#### G. 配置与交付物（对应 spec 6.4、7）

| 新增功能点 | 输入 | 输出 | 核心逻辑 | 依赖 |
|-----------|------|------|---------|------|
| 规则配置对象 | 调用方参数 / JSON 配置 | `RuleConfig` | 阈值、目录映射、高危/可疑/敏感特征集中定义；非法值回退默认并给出中文提示；固定项不可覆盖 | A～F |
| 依赖清单 | — | `backend/requirements.txt` | 仅标准库，文件内容仅注释说明，不列出第三方包 | 无 |
| 样例变更清单 | — | `backend/tests/fixtures/sample_changes.txt` | 覆盖 A/M/D、中文名、错目录、缺注释、异常链接、大文件、疑似密钥、空行、注释行 | 无 |
| 使用说明 | — | `docs/rules_engine_usage.md` | 中文说明清单生成、入口调用、两类级别阅读方式 | 无 |

## 1.2 存量功能详细分析

### 1.2.1 目录骨架的接口契约与约束

| 路径 | 现状 | 约束 | 对设计的影响 |
|------|------|------|-------------|
| `backend/app/` | 空目录，含 `api/`、`core/`、`db/`、`models/`、`services/` 子目录 | 无 `__init__.py`，不可作为包导入 | 必须补齐 `app/__init__.py`；`rules` 子包只依赖自身与标准库，禁止导入同级的空业务目录 |
| `backend/app/core/rules/` | 空目录 | 交付物验收要求该目录下存在四个检查模块与一个汇总入口（spec 7.1 第 1 条） | 五个业务文件必须位于该目录顶层；数据结构、配置、清单解析、IO、渲染下沉到 `common/` 子包，避免顶层文件数量膨胀 |
| `backend/tests/` | 空目录 | 无测试框架、无 fixtures | 测试使用标准库 `unittest`；样例清单放在 `backend/tests/fixtures/` |
| `docs/` | 空目录 | 需承载中文使用说明（spec 7 第 8 条） | 新增 `docs/rules_engine_usage.md`，不与其他组件文档冲突 |

**约束结论**：
1. Python 包根必须是 `backend/`，所有模块以 `app.core.rules.*` 形式导入；运行命令的工作目录固定为 `backend/`。
2. 不能假设存在 Web 框架、数据库驱动或第三方工具；`requirements.txt` 保持"零第三方依赖"是本设计最关键的工程约束。
3. 空目录不会被 Git 跟踪，实现阶段必须在五个业务文件中至少写入内容，否则交付路径在版本库中不可见。

### 1.2.2 样例仓库现状与复用边界

| 路径 | 现状 | 可复用点 | 限制 |
|------|------|---------|------|
| `demo-repo/` | 存在，含 `docs/`、`lab/`、`notes/` 空目录 | 可作为 `--repo` 根，目录名天然覆盖"文档目录/源码目录/笔记目录"三类归属场景 | 无任何文件，样例清单引用的文件需实现阶段创建；不能把样例文件放到 `backend/` 下，否则污染被测代码库 |
| `codearts_proof/`、`ppt/`、`video/`、`frontend/` | 空目录 | 与本组件无关 | 不得写入、不得扫描（避免大文件视频进入样例） |

**结论**：样例清单以 `demo-repo/` 为相对根；测试的端到端用例同时提供"临时目录工厂"，不依赖开发者手工准备文件。

### 1.2.3 运行环境现状与风险

| 项目 | 现状 | 影响 | 缓解措施 |
|------|------|------|---------|
| Python 解释器 | `python --version` 报错（`D:\python\python.exe` 无法启动），`where python` 指向 WindowsApps 存根 | 规则引擎与测试暂时无法直接运行 | 设计只依赖 Python 3.10+ 标准库（`ast`、`dataclasses`、`argparse`、`unittest`、`json`），环境修复后无需安装任何包；实现阶段先验证解释器，再执行测试 |
| Node.js | 24.19.0 可用 | 与本组件无关 | 不引入 JS 工具链，不修改 `frontend/` |
| Git | 当前目录不是 Git 仓库 | 无法用 `git diff` 生成清单 | 变更清单由调用方生成并以文本传入（spec 1.4 已明确不负责 Git 操作），不影响设计 |
| 换行与编码 | Windows 环境，CRLF 常见 | 行解析、链接行号、BOM 易出错 | 统一按 `splitlines()` 处理并去除 BOM；输出统一 `\n`；路径统一 `/` |

### 1.2.4 与上下游组件的边界契约

| 上游/下游 | 交互方式 | 契约约束 | 设计落点 |
|-----------|---------|---------|---------|
| 终端 CLI（学生/助教/维护者） | 进程调用，一次性执行 | 中文摘要、稳定退出码、不输出英文堆栈 | `engine.main()` + `render_text()` |
| CI 脚本 / Git 变更记录 | 进程调用或进程内调用 | 读取结构化 JSON 与退出码；不得依赖终端文案 | `run_check*()` + `report_to_json()` |
| 未来 Web 服务（`app.api`/`app.services`） | 进程内函数调用 | 返回可 JSON 序列化的内存对象；不得有全局可变状态；不得写文件 | `CheckReport` 为不可变 dataclass；入口无副作用 |
| 本地文件系统 | 只读 | 不写、不改、不移动、不删除；不读取仓库外文件 | `FileSnapshot` + 路径沙箱 |

### 1.2.5 存量分析结论

1. **无存量业务逻辑可复用**：spec 5.1～5.6 的所有判定规则、数据结构、汇总流程、退出码均为新增，匹配度 0%。
2. **存量仅提供路径约束**：五个业务文件的落盘目录、测试目录、样例仓库根已被骨架固定，设计必须"就位交付"，不能引入新的顶层工程结构。
3. **最大设计约束是环境**：零第三方依赖、Python 3.10+、Windows/Linux 一致、只读离线，这四点贯穿后续全部模块设计。
4. **接口契约从本阶段开始成为"未来存量"**：`run_check()` 的签名、`Finding` 的字段、`rule_id` 的命名必须在后续版本保持稳定（spec 4.4 第 1 条）。

# 二、增量设计方案

## 2.1 实现模型

### 2.1.1 上下文视图

规则引擎是一个**进程内可调用、同时可命令行运行**的独立能力单元：上游为终端命令、CI 脚本与未来的 Web 服务，下游只有本地文件系统（只读）。它不访问网络、不访问数据库、不调用 Git。

```plantuml
@startuml
skinparam componentStyle rectangle
skinparam defaultFontName "Microsoft YaHei"

actor "学生贡献者" as Student
actor "助教 / 维护者" as TA
actor "CI 流水线" as CI

node "终端命令行" as CLI
node "未来 Web 服务\n(app.api / app.services)" as Web

component "RepoGuard 规则引擎\napp.core.rules" as Engine

node "本地文件系统（只读）" as FS
node "变更清单文件\n（调用方生成）" as Manifest

Student --> CLI : 单次自检
TA --> CLI : 批量巡检
CLI --> Engine : 清单文本 + 仓库根 + 配置（进程调用）
CI --> Engine : 清单文本 + 仓库根（进程调用）
Web --> Engine : 进程内函数调用
Manifest --> CLI : 提供文件
Engine --> FS : stat / 只读 open
FS --> Engine : 体积 / 文本 / 错误
Engine --> CLI : 中文摘要 + 退出码
Engine --> CI : JSON + 退出码
Engine --> Web : CheckReport（可 JSON 序列化）
@enduml
```

| 交互方 | 方向 | 协议/方式 | 频率 | 数据 |
|--------|------|----------|------|------|
| 终端 CLI | 上游 | `python -m app.core.rules.engine` 进程调用 | 每次提交前，人工触发 | 清单路径/文本、仓库根、格式选项 |
| CI 脚本 | 上游 | 进程调用，读取 stdout 与退出码 | 每次推送或合并请求 | 清单文本、仓库根 |
| 未来 Web 服务 | 上游 | 进程内 `import` 调用 | 按请求 | 清单文本、仓库根、`RuleConfig` |
| 本地文件系统 | 下游 | `os.stat` + `open("r"/"rb")`，只读 | 每文件 1 次体积查询、最多 1 次内容读取 | 体积、编码后文本、错误信息 |
| 网络 / 数据库 / Git | — | **不交互** | — | — |

### 2.1.2 服务/组件总体架构

```plantuml
@startuml
skinparam componentStyle rectangle
skinparam defaultFontName "Microsoft YaHei"

package "app.core.rules" {
  [engine.py\n唯一公共入口 / 调度 / 汇总] as Engine
  [naming.py\n命名与目录] as Naming
  [code_scan.py\n注释与高危写法] as Code
  [link_check.py\nMarkdown 链接] as Link
  [sensitive.py\n体积与敏感信息] as Sensitive

  package "common（内部支撑，不对外暴露）" {
    [models.py\n数据结构与校验] as Models
    [manifest.py\n清单解析与路径归一化] as Manifest
    [file_io.py\n快照 / 编码 / 沙箱] as IO
    [config.py\n默认阈值与特征清单] as Config
    [report.py\n中文摘要 / JSON] as Report
  }
}

[engine.py] --> [naming.py]
[engine.py] --> [code_scan.py]
[engine.py] --> [link_check.py]
[engine.py] --> [sensitive.py]
[engine.py] --> [common/manifest.py]
[engine.py] --> [common/report.py]
[engine.py] --> [common/models.py]
[naming.py] --> [common/models.py]
[code_scan.py] --> [common/models.py]
[link_check.py] --> [common/models.py]
[sensitive.py] --> [common/models.py]
[naming.py] --> [common/file_io.py]
[code_scan.py] --> [common/file_io.py]
[link_check.py] --> [common/file_io.py]
[sensitive.py] --> [common/file_io.py]
[engine.py] --> [common/file_io.py]
[engine.py] --> [common/config.py]
@enduml
```

| 组件 | 职责 | 允许依赖 | 禁止依赖 |
|------|------|---------|---------|
| `engine.py` | 唯一入口、清单加载、条目合并、四模块调度、异常隔离、分组排序、统计、状态判定、CLI | 四个检查模块、`common/*`、标准库 | `app.api`、`app.db`、`app.models`、`app.services`、任何第三方包 |
| `naming.py` | spec 5.2 全部判定，仅依据路径与扩展名，D 状态唯一可执行的模块 | `common/models`、`common/file_io`（只做路径归一化后的确认，不读内容） | 其余三个检查模块 |
| `code_scan.py` | spec 5.3，`.py`/`.c`/`.h` 注释与写法检查 | `common/models`、`common/file_io`、标准库 `ast`/`re` | 不执行/编译/导入被扫描代码 |
| `link_check.py` | spec 5.4，Markdown 链接结构检查 | `common/models`、`common/file_io`、`re`/`ipaddress` | 不联网、不读取链接目标内容 |
| `sensitive.py` | spec 5.5，体积与凭据检查 | `common/models`、`common/file_io`、`re`/`time` | 不调用外部服务校验密钥、不写日志文件 |
| `common/models.py` | 不可变数据结构、枚举、构造期校验、序列化字典 | 标准库 `dataclasses`/`enum` | 不依赖任何检查模块 |
| `common/manifest.py` | 逐行解析、状态归一化、路径归一化、重复合并 | `common/models` | 不访问文件系统（路径校验除外） |
| `common/file_io.py` | 快照缓存、只读读取、BOM/UTF-8/GB18030、二进制判定、路径沙箱 | `common/models` | 不写文件、不联网 |
| `common/config.py` | 默认阈值、目录映射、特征清单、配置合并与校验 | `common/models` | 不读配置文件以外的仓库内容 |
| `common/report.py` | 中文终端摘要、JSON 序列化、最小结构回退 | `common/models` | 不参与判定 |

**架构约束**：
1. 四模块彼此**零依赖**，只能经 `engine` 串联，保证任一模块可单独停用/替换。
2. `common` 是内部实现细节，`rules/__init__.py` 只导出公共入口与数据结构，不导出内部辅助函数。
3. 配置由 `engine` 一次性构造并注入 `CheckContext`，模块内不读取环境变量、不自行解析 JSON。

### 2.1.3 实现设计文档

#### （1）主流程活动图

```plantuml
@startuml
skinparam defaultFontName "Microsoft YaHei"
start
:校验 repo_root 存在且为目录;
if (不合法?) then (是)
  :生成“输入错误”报告\n不读取任何文件;
  stop
endif
:加载清单（文本或文件）;
if (清单不可读?) then (是)
  :生成“输入错误”报告\n附中文原因;
  stop
endif
:逐行解析 → entries + unparsed_lines;
if (无有效条目?) then (是)
  :返回空报告（全零统计）\n退出码 0;
  stop
endif
:按路径合并重复条目;
:构建 FileSnapshot 提供器（惰性）;
fork
  :naming.check（全部 A/M/D）;
fork again
  :code_scan.check（A/M 的 .py/.c/.h）;
fork again
  :link_check.check（A/M 的 .md）;
fork again
  :sensitive.check（A/M 全部文件）;
end fork
:逐模块捕获异常 → 降级列表;
:按文件分组 + 级别/行号排序;
:统计七项指标 + 判定 status;
:渲染中文摘要 / JSON（按需）;
:按优先级计算退出码;
stop
@enduml
```

> 图中的 fork 表达"逻辑上互不依赖的四个检查维度"，**实现选择串行执行**（决策理由见 2.12），以确保确定性、单文件读取次数可控、异常隔离边界清晰。

#### （2）报告状态机

```plantuml
@startuml
skinparam defaultFontName "Microsoft YaHei"
[*] --> 正常 : 入口参数合法且全部模块完成
[*] --> 输入错误 : 仓库根不存在 / 清单不可读 / 配置致命非法
[*] --> 部分降级 : 任一模块异常或序列化回退
正常 --> 部分降级 : 运行期模块异常
部分降级 --> 部分降级 : 其他模块继续失败
输入错误 --> [*]
正常 --> [*]
部分降级 --> [*]
@enduml
```

- `正常`：所有模块完成，允许存在"必须修改"问题（问题属于业务结果，不代表引擎故障）。
- `部分降级`：至少一个模块整体失败、或 JSON 序列化回退、或配置被回退为默认且影响判定。
- `输入错误`：仓库根非法、清单整体不可读；不进入文件检查阶段。
- 单文件跳过（不存在/无权限/编码失败/路径越界）**不改变** `status`，只进入 `skipped_file_count` 与文件分组说明。

#### （3）文件快照与"单文件单次读取"

| 设计点 | 方案 | 对应约束 |
|--------|------|---------|
| 快照创建 | `engine` 为每个规范化路径创建一个 `FileSnapshot`，四个模块共享同一实例 | spec 4.1 第 4 条：单模块不重复读取 |
| 体积 | 首次 `size` 属性触发一次 `os.stat`，结果缓存 | spec 4.1 第 3 条：大文件不整体读入 |
| 文本 | 首次 `text()` 才读取；读取后缓存；后续模块复用 | 四模块最多各调用一次，实际磁盘读取 1 次 |
| 编码 | 二进制 `rb` 读入后：去 UTF-8 BOM → `utf-8` 严格解码 → 失败回退 `gb18030` → 再失败标记 `ENCODING_ERROR` | spec 4.5 第 2、3 条 |
| 二进制 | 扩展名黑名单优先；否则读取前 8 KB 检测 `\x00`；二进制不进入文本缓存 | spec 5.5.1 第 3 条 |
| D 状态 | `engine` 不为 D 条目创建快照，仅传路径给 naming | spec 5.1.1 第 8 条、5.5.1 第 4 条 |
| 读取失败 | 快照记录 `error_kind`（不存在/无权限/编码/非法路径），`text()` 返回失败结果而非抛异常 | spec 4.2 第 2 条 |

#### （4）路径安全沙箱

1. 归一化：去首尾空白 → `\`→`/` → 反复去除 `./` 前缀 → 折叠 `//` → 消除 `.` 段。
2. 拒绝：以 `/` 开头、`^[A-Za-z]:` 盘符、`^//` UNC、归一化后仍含 `..` 段。
3. 解析：`realpath(repo_root / rel_path)`（解析符号链接）后与 `realpath(repo_root)` 做 `commonpath` 比较；Windows 下双方 `casefold()` 后比较，避免大小写差异绕过。
4. 只读：合法路径才允许 `stat/open`；非法路径直接生成"非法路径"跳过说明，**不产生任何文件系统调用**（spec 4.3 第 3 条、5.1.1 第 10 条）。

#### （5）确定性设计

| 风险来源 | 控制措施 |
|---------|---------|
| 遍历顺序 | 不使用 `os.walk`；只按清单条目顺序处理，最终显式排序 |
| 集合/字典输出 | 内部可用 `set` 去重，输出前必须转为排序后的 `tuple` |
| 排序受语言环境影响 | 使用 Unicode 码点排序，不使用 `locale.strxfrm` |
| 时间戳/绝对路径 | 报告不包含时间戳、主机名、绝对路径 |
| 并发 | 本轮不启用多线程/多进程，避免 I/O 与异常顺序不确定 |
| 浮点阈值 | 体积统一用字节整数比较，阈值换算一次后取整，避免浮点误差 |

#### （6）只读与离线保障

- 仅调用 `os.stat`、`open(..., "r"/"rb")`；不存在任何 `write`/`unlink`/`rename`/`makedirs` 调用路径。
- 不导入 `requests`、`urllib.request`、`socket`、`http.client`；链接检查只做字符串结构判定。
- 不调用 `subprocess` 执行被扫描文件；`subprocess` 仅作为**被检测的关键字**出现在特征清单中。
- CLI 仅在调用方显式传入 `--output` 时写一个 JSON 文件到指定路径，默认只写 stdout。

#### （7）超时与资源控制

| 场景 | 预算 | 实现策略 | 超预算行为 |
|------|------|---------|-----------|
| 单文件全部检查 | 300 ms（spec 4.1 第 2 条） | 每模块在行循环中按每 200 行检查一次 `perf_counter` | 提前结束该模块对该文件的扫描，附"内容检查未完成"说明，不中断其他文件 |
| > 5 MB 文本内容扫描 | 1 s（spec 4.1 第 2 条） | 64 KB 分块 + 每块检查时间 | 保留体积结论，提示"文件过大，仅完成体积检查" |
| 单次执行总量 | 10 s / 500 条 / 100 个可读文件 | 快照复用 + 预编译正则 + 无重复读取 | 不做硬性中断（避免漏检），通过测试基准约束实现效率 |
| 内存峰值 | 200 MB | 大文件分块读取；二进制不缓存全文；快照仅缓存需要扫描的文本 | 超大文本只保留匹配所需的块 |

## 2.2 接口设计

### 2.2.1 总体设计

接口分为三层，稳定性等级如下（"稳定"= 后续版本不得破坏签名与语义）：

| 层级 | 接口 | 使用方 | 稳定性 | 说明 |
|------|------|--------|--------|------|
| 公共 API | `run_check()` / `run_check_file()` | CLI、CI、未来 Web 服务 | 稳定 | 唯一推荐入口，返回完整 `CheckReport`，不抛业务异常 |
| 公共 API | `render_text()` / `report_to_json()` / `report_to_dict()` | CLI、CI、Web | 稳定 | 只做渲染，不含判定逻辑 |
| 公共 API | `RuleConfig` 及默认配置 | 调用方 | 稳定（字段只增不改） | 配置以关键字参数覆盖 |
| 模块 SPI | `check(entry, ctx) -> ModuleResult` | 内部/扩展开发者 | 实验（本版本内部） | 四模块统一契约；新增模块可按此接入 |
| CLI | `main(argv) -> int` | 终端、CI | 稳定 | 参数只增不减；退出码语义固定 |

**版本策略**：
- 公共函数签名只做"新增可选参数"，不改变现有参数顺序与含义。
- `Finding`/`CheckReport` 新增字段必须带默认值；JSON 消费方需容忍未知字段。
- `rule_id` 一经发布不得修改（spec 4.4 第 1 条），弃用规则保留标识并在配置中关闭，不删除历史标识。

> **口径统一声明（本次修订）**：2.2.2 给出的是接口语义与稳定性约定；自本次修订起，**实现文件归属与完整类型注解以 2.4.3 为权威口径**。若两处表述不一致（如渲染函数的实现文件、辅助函数参数、`CheckContext` 类型），以 2.4.3 为准；2.2 的参数顺序与语义保持不变，差异清单见 2.4.5。

### 2.2.2 接口清单

#### （1）公共入口：执行检查

```python
def run_check(
    manifest_text: str,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...
```

- **业务说明**：接收内存中的变更清单文本，执行四类检查并返回汇总报告。适用于 CI、Web 服务与测试。
- **前置条件**：`manifest_text` 为 `str`（允许空串、注释行）；`repo_root` 为仓库根路径；`config` 为 `None` 时使用默认配置。
- **后置条件**：返回结构完整的 `CheckReport`；不修改仓库任何文件；不发起网络请求。
- **异常映射**：内部业务异常一律转为报告字段，不向调用方抛出；仅 `MemoryError`/`KeyboardInterrupt`/`SystemExit` 不拦截。
- **幂等性**：相同输入与相同仓库内容，`report_to_json()` 输出逐字节一致。

```python
def run_check_file(
    manifest_path: str | Path,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...
```

- **业务说明**：从文件读取清单（UTF-8 / BOM 容忍 / GB18030 回退）后调用 `run_check()`。
- **前置条件**：路径存在且可读。
- **后置条件**：成功时与 `run_check(文件内容, ...)` 结果完全一致。
- **异常映射**：文件不可读 → `status="输入错误"`，`warnings` 含"无法读取变更清单：<路径>，请确认文件存在且可读"，`summary` 全零，退出码 2；**不抛异常**。

**调用示例**：

```python
from pathlib import Path
from app.core.rules import run_check, render_text, report_to_json

report = run_check(
    manifest_text="A docs/lab03_串口通信实验.md\nM lab/uart/uart_demo.c\n",
    repo_root=Path("../demo-repo"),
)
print(render_text(report))
json_text = report_to_json(report)  # ensure_ascii=False
```

#### （2）渲染接口

```python
def render_text(report: CheckReport) -> str: ...
def report_to_dict(report: CheckReport) -> dict[str, object]: ...
def report_to_json(report: CheckReport) -> str: ...
```

| 接口 | 业务说明 | 前置 | 后置 | 异常映射 |
|------|---------|------|------|---------|
| `render_text` | 生成中文终端摘要：先必须修改、后优化建议，按文件分组，附统计/跳过/降级 | `report` 为合法对象 | 返回以 `\n` 连接的文本，不含 ANSI 颜色码 | 内部异常 → 调用方（engine）降级 |
| `report_to_dict` | 转为可 JSON 序列化的最小字典 | 同上 | 键名与 2.3 字段表一致；枚举转中文值 | 附加字段不可序列化时丢弃并记录警告 |
| `report_to_json` | `json.dumps(..., ensure_ascii=False, indent=2)` | 同上 | UTF-8 友好字符串，中文不转义 | 失败 → 回退四必填字段最小结构 + 降级说明（spec 5.6.3 第 5 条） |

#### （3）模块 SPI

```python
def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...
```

| 项 | 约定 |
|----|------|
| 输入 | `entry` 为已归一化条目；`ctx` 提供 `repo_root`、`config`、`snapshot(path)`、`module_name` |
| 输出 | `ModuleResult(findings: tuple[Finding, ...], skip_reason: str \| None)` |
| 适用状态 | naming：A/M/D；code_scan/link_check/sensitive：仅 A/M |
| 前置 | `entry.path` 已通过沙箱校验；D 状态不得调用 `ctx.snapshot()` |
| 后置 | 返回的每条 `Finding.file_path == entry.path`；不读写仓库；不缓存跨文件状态 |
| 异常 | 允许抛 `Exception`，由 `engine` 捕获并记 `DegradedModule(module, 中文原因)`；模块自身不得吞掉"整体失败" |
| 确定性 | 内部聚合与排序后返回；同一文件重复调用结果一致 |

#### （4）清单解析接口

```python
def parse_manifest(manifest_text: str) -> ManifestParseResult: ...
```

- **业务说明**：把原始清单转为规范化条目与非法行清单，不访问文件系统。
- **前置**：文本可为空。
- **后置**：`entries` 保持首次出现顺序；`unparsed_lines` 按行号升序；注释行与空行不进入任何列表。
- **异常映射**：内部异常由 `engine` 转为"输入错误"报告；正常解析不抛异常。

#### （5）命令行接口

```text
python -m app.core.rules.engine --manifest <清单路径|-> --repo <仓库根>
                                [--format text|json] [--output <文件路径>]
                                [--config <JSON 配置路径>] [--debug]
```

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--manifest` | 是 | — | 清单文件路径；`-` 表示从 stdin 读取 |
| `--repo` | 否 | 当前工作目录 | 被检查仓库根 |
| `--format` | 否 | `text` | `text` 输出中文摘要；`json` 输出结构化 JSON |
| `--output` | 否 | 无 | 显式指定时写 JSON 到该路径；默认只写 stdout |
| `--config` | 否 | 无 | 规则配置 JSON；非法值回退默认并提示 |
| `--debug` | 否 | 关闭 | 仅此模式下向 stderr 输出异常堆栈，正常模式禁止英文堆栈 |

**CLI 调用示例**：

```bash
cd backend
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo
```

## 2.3 数据模型

### 2.3.1 设计目标

1. **术语对齐**：字段命名与 spec 第 2 章领域术语一致（变更清单、问题、问题级别、汇总报告），不引入"告警/错误/警告"等混用概念。
2. **强类型**：级别、状态、报告状态、退出码使用枚举，禁止以字符串裸传；`level` 构造期校验，非法值立即拒绝。
3. **不可变与确定性**：对外报告对象使用冻结 dataclass 与元组，避免调用方或模块间共享可变状态导致结果漂移。
4. **可序列化**：所有对象可无损转 JSON；不包含 `Path`、`datetime`、异常对象等不可序列化字段；中文不转义。
5. **可追溯**：每条 `Finding` 携带稳定 `rule_id`，可选 `line_no`/`excerpt`，支撑 spec 4.4 第 1 条与 6.2 约束。
6. **内存约束**：不持久化、不落库；单次执行只保留报告所需数据，超长原文截断（`raw` ≤ 500，`excerpt` ≤ 60）。

### 2.3.2 模型实现

```plantuml
@startuml
skinparam defaultFontName "Microsoft YaHei"
skinparam classAttributeIconSize 0

class ChangeEntry {
  +status : ChangeStatus
  +path : str
  +line_no : int
  +raw : str | None
  +duplicate_count : int
}

class UnparsedLine {
  +line_no : int
  +raw : str
  +reason : str
}

class Finding {
  +level : IssueLevel
  +file_path : str
  +message : str
  +suggestion : str
  +rule_id : str
  +line_no : int | None
  +excerpt : str | None
}

class FileGroup {
  +file_path : str
  +status : ChangeStatus
  +findings : tuple[Finding, ...]
  +skip_reason : str | None
  +duplicate_count : int
}

class CheckSummary {
  +entry_count : int
  +issue_count : int
  +must_fix_count : int
  +suggestion_count : int
  +skipped_file_count : int
  +degraded_module_count : int
  +unparsed_line_count : int
}

class DegradedModule {
  +module : str
  +reason : str
}

class CheckReport {
  +status : ReportStatus
  +summary : CheckSummary
  +files : tuple[FileGroup, ...]
  +unparsed_lines : tuple[UnparsedLine, ...]
  +degraded_modules : tuple[DegradedModule, ...]
  +warnings : tuple[str, ...]
}

class ManifestParseResult {
  +entries : tuple[ChangeEntry, ...]
  +unparsed_lines : tuple[UnparsedLine, ...]
}

class ModuleResult {
  +findings : tuple[Finding, ...]
  +skip_reason : str | None
}

class FileSnapshot {
  +path : str
  +size : int
  +is_binary : bool
  +read_error : str | None
  +text() : TextReadResult
}

CheckReport "1" *-- "1" CheckSummary
CheckReport "1" *-- "0..*" FileGroup
CheckReport "1" *-- "0..*" UnparsedLine
CheckReport "1" *-- "0..*" DegradedModule
FileGroup "1" *-- "0..*" Finding
ManifestParseResult "1" *-- "0..*" ChangeEntry
ManifestParseResult "1" *-- "0..*" UnparsedLine
ModuleResult "1" *-- "0..*" Finding
@enduml
```

#### （1）枚举定义

| 枚举 | 取值 | 语义 | 约束 |
|------|------|------|------|
| `ChangeStatus` | `A` / `M` / `D` | 新增 / 修改 / 删除 | 输入小写归一化为大写；其他值不构造条目 |
| `IssueLevel` | `必须修改` / `优化建议` | 问题级别 | 仅两个值；禁止英文值 |
| `ReportStatus` | `正常` / `部分降级` / `输入错误` | 报告整体状态 | 见 2.1.3 状态机 |
| `ExitCode` | `OK=0` / `MUST_FIX=1` / `INPUT_ERROR=2` / `EXECUTION_ERROR=3` | 命令行退出状态 | 见 2.7.2 |

#### （2）`ChangeEntry` 字段约束

| 字段 | 类型 | 必填 | 约束 | spec 来源 |
|------|------|------|------|----------|
| `status` | `ChangeStatus` | 是 | A/M/D，小写归一化 | 6.1 第 1 条、5.1.1 第 2、3 条 |
| `path` | `str` | 是 | 非空、`/` 分隔、不以 `/` 或盘符开头、不含越界 `..` | 6.1 第 2 条、5.1.1 第 4 条 |
| `line_no` | `int` | 是 | ≥ 1，首次出现行号 | 6.1 第 3 条 |
| `raw` | `str \| None` | 否 | 原始行，≤ 500 字符，超长截断 | 6.1 第 4 条 |
| `duplicate_count` | `int` | 是 | ≥ 1；重复路径取最后一次状态 | 5.1.1 第 7 条、6.1 第 5 条 |

#### （3）`Finding` 字段约束

| 字段 | 类型 | 必填 | 约束 | spec 来源 |
|------|------|------|------|----------|
| `level` | `IssueLevel` | 是 | 非空，仅"必须修改/优化建议" | 6.2 第 1 条 |
| `file_path` | `str` | 是 | 与所属 `FileGroup.file_path` 完全一致 | 6.2 第 2 条 |
| `message` | `str` | 是 | 中文陈述句，8～200 字符 | 6.2 第 3 条 |
| `suggestion` | `str` | 是 | 中文可执行建议，≤ 300 字符，含示例/目标路径 | 6.2 第 4 条 |
| `rule_id` | `str` | 是（设计上强制） | `模块前缀-三位序号`，如 `naming-001` | 6.2 第 5 条、4.4 第 1 条 |
| `line_no` | `int \| None` | 否 | ≥ 1；代码/链接/敏感类问题必须提供 | 6.2 第 6 条、5.3.1 第 8 条 |
| `excerpt` | `str \| None` | 否 | ≤ 60 字符；敏感内容必须脱敏 | 6.2 第 7 条、5.4.1 第 10 条、5.5.1 第 9 条 |

> 说明：spec 6.2 将 `rule_id` 标为"可选"，本设计将其提升为**实现层必填**，以满足 spec 4.4 第 1 条"每条问题必须携带稳定规则标识"；对外 JSON 中该字段始终存在。

#### （4）`CheckSummary` 统计口径

| 字段 | 含义 | 计算口径 | spec 来源 |
|------|------|---------|----------|
| `entry_count` | 条目总数 | 合并重复路径后的条目数 | 5.6.1 第 4 条 |
| `issue_count` | 问题总数 | 所有 `Finding` 数量 | 5.6.1 第 4 条 |
| `must_fix_count` | 必须修改数量 | `level == 必须修改` 的数量 | 5.6.1 第 4 条 |
| `suggestion_count` | 优化建议数量 | `level == 优化建议` 的数量 | 5.6.1 第 4 条 |
| `skipped_file_count` | 跳过文件数 | 带 `skip_reason` 的文件分组数 | 1.3 第 2 条、4.2 第 2 条 |
| `degraded_module_count` | 降级模块数 | `degraded_modules` 长度 | 1.3 第 2 条、4.2 第 3 条 |
| `unparsed_line_count` | 无法解析行数 | `unparsed_lines` 长度（单列） | 5.6.1 第 4 条 |
| `warnings`（扩展） | 提示信息 | 配置回退、序列化回退、空清单提示等 | 5.6.1 第 10 条 |

**一致性不变量**（构造期断言）：
- `issue_count == must_fix_count + suggestion_count`
- `must_fix_count == Σ(各分组必须修改数)`，`suggestion_count` 同理
- `skipped_file_count == count(files where skip_reason is not None)`
- `degraded_module_count == len(degraded_modules)`
- `unparsed_line_count == len(unparsed_lines)`

#### （5）对象生命周期与持久化

| 阶段 | 动作 | 可变性 |
|------|------|--------|
| 解析 | `parse_manifest` 产出 `ManifestParseResult`（元组） | 不可变 |
| 执行 | 各模块返回 `ModuleResult`；`engine` 内部用列表临时聚合 | 临时可变，不对外暴露 |
| 汇总 | 构造 `FileGroup`/`CheckSummary`/`CheckReport` | 冻结 dataclass |
| 渲染 | `report_to_dict` 生成新字典；不改原对象 | 无副作用 |
| 持久化 | 无数据库、无缓存文件；仅 `--output` 显式写 JSON | 不写仓库 |

#### （6）配置驱动的数据形态

`RuleConfig` 为冻结 dataclass，模块只读；映射类字段统一存为不可变元组/只读映射，避免运行期被模块篡改。完整字段见 2.8。

## 2.4 目录与模块划分

### 2.4.1 目录结构

```text
RepoGuard/
├── backend/
│   ├── __init__.py                     # 不新增（以 backend/ 为工作目录，app 为顶层包）
│   ├── requirements.txt                # 交付物：零第三方依赖，仅注释说明
│   ├── app/
│   │   ├── __init__.py                 # 扩展：包标记
│   │   └── core/
│   │       ├── __init__.py             # 扩展：包标记
│   │       └── rules/
│   │           ├── __init__.py         # 对外导出 run_check/run_check_file/render_text/report_to_json
│   │           ├── naming.py           # 交付物 1：命名与目录归属（spec 5.2）
│   │           ├── code_scan.py        # 交付物 2：代码注释与高危写法（spec 5.3）
│   │           ├── link_check.py       # 交付物 3：Markdown 链接格式（spec 5.4）
│   │           ├── sensitive.py        # 交付物 4：大文件与敏感信息（spec 5.5）
│   │           ├── engine.py           # 交付物 5：清单解析调度与汇总入口（spec 5.1、5.6）
│   │           └── common/             # 内部支撑包（不对外暴露）
│   │               ├── __init__.py
│   │               ├── models.py       # 数据结构、枚举、构造期校验
│   │               ├── config.py       # 默认配置、目录映射、特征清单、配置合并
│   │               ├── manifest.py     # 逐行解析、路径归一化、重复合并
│   │               ├── file_io.py      # 快照、只读读取、编码回退、二进制、沙箱
│   │               └── report.py       # 中文摘要、JSON 序列化、最小结构回退
│   └── tests/
│       ├── fixtures/
│       │   └── sample_changes.txt      # 交付物：样例变更清单（UTF-8 无 BOM）
│       ├── test_manifest.py
│       ├── test_naming.py
│       ├── test_code_scan.py
│       ├── test_link_check.py
│       ├── test_sensitive.py
│       ├── test_engine.py
│       └── test_cli.py
├── demo-repo/                          # 样例仓库根（实现阶段补充最小样例文件）
│   ├── docs/
│   ├── lab/
│   └── notes/
└── docs/
    └── rules_engine_usage.md           # 交付物：中文使用说明（spec 7 第 8 条）
```

> **路径核对（与 2.4.3 一致）**：上述全部产品 `.py` 均位于 `backend/app/` 之下；`backend/tests/` 与 `demo-repo/` 下的 `.py` 分别为测试资产与样例数据，不是产品源码，详见 2.4.3（1）。

### 2.4.2 模块职责与导入规则

| 层级 | 文件 | 职责 | 允许导入 | 禁止导入 |
|------|------|------|---------|---------|
| 公共层 | `rules/__init__.py` | 只做再导出，不含逻辑 | `engine`、`common.models`、`common.config` | 各检查模块的内部私有函数 |
| 编排层 | `rules/engine.py` | 参数校验、清单加载、条目合并、调度、异常隔离、分组排序、统计、CLI、退出码 | 四模块、`common.*`、`argparse`/`json`/`pathlib` | `app.api`、`app.db`、`app.models`、`app.services` |
| 规则层 | `rules/naming.py` 等四个 | 单一检查主题的判定与文件内聚合 | `common.models`、`common.file_io`、标准库 | 其他规则模块、`engine`（防止循环依赖） |
| 支撑层 | `common/models.py` | 不可变数据结构与校验 | `dataclasses`/`enum`/`re` | 任何规则模块、文件系统 |
| 支撑层 | `common/manifest.py` | 解析与归一化 | `common.models`、`re` | 规则模块、`engine` |
| 支撑层 | `common/file_io.py` | 只读文件访问与安全校验 | `common.models`、`os`/`pathlib`/`codecs` | `engine`、规则模块 |
| 支撑层 | `common/config.py` | 默认值与配置合并 | `common.models`、`json` | `file_io`（配置不读仓库文件，除非 CLI 显式 `--config`） |
| 支撑层 | `common/report.py` | 渲染与序列化 | `common.models`、`json` | 规则模块 |

**关键约束**：
1. `rules/` 顶层恰好五个业务文件 + `__init__.py`，满足 spec 7.1 第 1 条"四个检查模块与一个汇总入口共五个文件"的存在性验收；辅助能力全部下沉到 `common/`，不增加顶层交付噪音。
2. 不存在 `cli.py`/`__main__.py`：`python -m app.core.rules.engine` 依赖 `engine.py` 末尾的 `if __name__ == "__main__": raise SystemExit(main())`，保持交付文件数量与 spec 一致。
3. 运行工作目录固定为 `backend/`，包名为 `app.core.rules`；若从仓库根运行需使用 `python -m backend.app.core.rules.engine` 并额外补 `backend/__init__.py`，本设计**不推荐**该方式，避免与 `backend/` 内的相对资源路径耦合。
4. 所有文件 UTF-8 无 BOM 保存；`.gitattributes` 不在本阶段新增。

> **本次修订补充（2.4.3～2.4.5）**：2.4.2 给出的是层级级导入约束；自本次修订起，**文件级完整路径、公开函数签名与导入方向**以 2.4.3、2.4.4 为权威口径。2.2 的接口语义继续有效，差异统一记录在 2.4.5。

### 2.4.3 交付文件清单与函数签名（权威口径）

> 本节是 rules_engine 的**实现契约基线**。修订目标：①所有产品 Python 源码统一位于 `backend/app/` 下；②四个检查模块固定位于 `backend/app/core/rules/`；③`engine.py` 是唯一汇总入口；④每个文件的仓库相对路径、模块职责与全部公开函数签名在此固定，实现阶段不得自行增删公共符号。
>
> 术语说明：spec 中的「问题（Finding）」与调用方常说的 `Issue` 是同一概念。为避免双名，本设计**统一使用 `Finding`**，不新增 `Issue` 类型别名；`CheckReport` 仍是汇总报告根对象。

#### （1）路径合规核对

**口径定义**：

- **产品源码**：会被 `app.core.rules` 导入、参与规则引擎运行的 `.py`，必须全部位于 `backend/app/` 下。
- **测试资产**：`backend/tests/**/*.py`，仅由标准库 `unittest` 加载，不被产品代码导入。
- **样例数据**：`demo-repo/**/*.py`，仅作为"被扫描文件"，禁止被引擎导入。

| 类别 | 仓库相对路径范围 | 文件数 | 是否产品源码 | 是否进入 `app.core.rules` 导入图 | 越界判定 |
|------|-----------------|--------|-------------|------------------------------|---------|
| 产品源码 | `backend/app/**/*.py` | 14 | 是 | 是 | 0 项越界 |
| 测试资产 | `backend/tests/test_*.py` | 7 | 否 | 否（仅测试进程加载） | 设计允许的非产品资产 |
| 样例数据 | `demo-repo/backend/app/example_config.py`、`demo-repo/backend/tests/test_demo.py` | 2 | 否 | 否（仅作为被扫描对象） | 设计允许的非产品资产 |
| 非 Python 交付 | `backend/requirements.txt`、`backend/tests/fixtures/sample_changes.txt`、`docs/rules_engine_usage.md` | 3 | 否 | 否 | 不适用 |

**核对结论**：

1. 产品源码 14 个 `.py` **100% 位于 `backend/app/` 之下**；`backend/` 根目录、`scripts/`、`frontend/`、`demo-repo/` 之外的仓库根目录均不存在产品 `.py`。
2. 五个交付业务文件（`naming.py`、`code_scan.py`、`link_check.py`、`sensitive.py`、`engine.py`）全部位于 `backend/app/core/rules/` **顶层**，满足 spec 7.1 第 1 条"四个检查模块与一个汇总入口共五个文件"。
3. `common/` 支撑包 5 个 `.py` 与 4 个包标记 `__init__.py` 同样位于 `backend/app/` 下，不产生新的顶层工程结构。
4. `backend/tests/**` 的 7 个测试 `.py` 属于验收测试资产，不被产品代码导入；`demo-repo/**` 下的 2 个 `.py` 属于样例仓库数据，只作为被扫描对象。二者不是"规则引擎源码"，不计入路径越界；若验收脚本要求"仓库内全部 `.py` 均在 `backend/app/`"，必须显式排除这两类非产品资产。
5. 本节所有仓库相对路径统一使用 `/` 分隔，与 spec 4.5 第 5 条一致。
6. 按"仓库内全部 `.py`"计数：产品源码 14 个 + 测试资产 7 个 + 样例数据 2 个 = 23 个；其中仅产品源码 14 个进入 `backend/app/` 导入图，产品源码越界路径为 0 项。

#### （2）文件清单与职责

> "公开符号"指模块级、不带 `_` 前缀的名称；`_` 前缀函数、内部类与临时变量均为私有实现，不属于本节契约。

| 序号 | 仓库相对完整路径 | 类别 | 模块职责（一句话） | 对外公开符号 | 覆盖 rule_id / 数据 |
|------|-----------------|------|-------------------|-------------|-------------------|
| 1 | `backend/app/__init__.py` | 包标记 | 声明 `app` 顶层包，不承载逻辑 | `__all__`（空元组） | — |
| 2 | `backend/app/core/__init__.py` | 包标记 | 声明 `app.core` 包，不承载逻辑 | `__all__`（空元组） | — |
| 3 | `backend/app/core/rules/__init__.py` | 公共门面 | 只做稳定公共 API 的再导出，不含判定逻辑 | 见 2.4.3（4）导出表 | 全部 |
| 4 | `backend/app/core/rules/engine.py` | 汇总入口 | 清单加载、条目合并、四模块调度、异常隔离、分组排序、统计、CLI 与退出码 | `run_check`、`run_check_file`、`build_arg_parser`、`main`、`exit_code_for` | spec 5.1、5.6；汇总全部 `Finding` 为 `CheckReport` |
| 5 | `backend/app/core/rules/naming.py` | 检查模块 1 | 命名与目录归属检查，仅依据路径与扩展名，不读取内容 | `check`、`check_naming`、`check_directory`、`suggest_file_name`、`suggest_directory`、`is_test_file` | `naming-001`～`naming-006` |
| 6 | `backend/app/core/rules/code_scan.py` | 检查模块 2 | `.py`/`.c`/`.h` 注释、高危写法与可疑写法检查 | `check`、`detect_language`、`build_code_view`、`scan_python_source`、`scan_c_source` | `code-001`～`code-008` |
| 7 | `backend/app/core/rules/link_check.py` | 检查模块 3 | Markdown 链接结构、引用定义与协作适配检查 | `check`、`strip_code_blocks`、`extract_links`、`validate_links`、`LinkRecord` | `link-001`～`link-008` |
| 8 | `backend/app/core/rules/sensitive.py` | 检查模块 4 | 体积分级、凭据特征检测、教学豁免与脱敏 | `check`、`check_file_size`、`scan_secrets`、`mask_secret`、`is_placeholder_context` | `sens-001`～`sens-007` |
| 9 | `backend/app/core/rules/common/__init__.py` | 内部包标记 | 声明 `common` 内部包，禁止再导出 | `__all__`（空元组） | — |
| 10 | `backend/app/core/rules/common/models.py` | 数据结构 | 枚举、冻结 dataclass、`Finding` 构造、同类合并、报告构造与不变量校验 | `make_finding`、`merge_findings`、`empty_summary`、`build_report`、`validate_report` | 承载全部 `rule_id` 与 `Finding`/`CheckReport` |
| 11 | `backend/app/core/rules/common/config.py` | 配置 | 默认阈值、目录映射、特征清单、配置合并与非法值回退 | `RuleConfig`、`PatternSpec`、`ConfigBuildResult`、`DEFAULT_CONFIG`、`default_config`、`config_from_mapping`、`load_config_file`、`build_config` | 阈值与特征支撑全部模块 |
| 12 | `backend/app/core/rules/common/manifest.py` | 清单解析 | 逐行解析、状态归一化、路径归一化、重复合并、清单文件读取 | `ManifestReadError`、`parse_manifest`、`parse_manifest_line`、`normalize_path`、`has_escaping_segments`、`merge_entries`、`load_manifest_text` | `ChangeEntry`、`UnparsedLine` |
| 13 | `backend/app/core/rules/common/file_io.py` | 只读 IO | 路径沙箱、文件快照缓存、编码回退、二进制判定、模块上下文 | `resolve_repo_path`、`create_snapshot`、`read_text_from_disk`、`is_binary_file`、`FileSnapshot`、`CheckContext`、`TextReadResult`、`ReadErrorKind`、`ResolvedPath` | 支撑全部模块的单次读取与沙箱 |
| 14 | `backend/app/core/rules/common/report.py` | 渲染 | 中文终端摘要、字典/JSON 序列化、最小结构回退 | `render_text`、`report_to_dict`、`report_to_json` | 输出全部 `CheckReport` |

#### （3）数据结构归属与公共函数签名

**归属口径**：

- `common/models.py`：`ChangeStatus`、`IssueLevel`、`ReportStatus`、`ExitCode`、`ChangeEntry`、`UnparsedLine`、`Finding`、`FileGroup`、`CheckSummary`、`DegradedModule`、`CheckReport`、`ManifestParseResult`、`ModuleResult`，以及构造、合并与不变量校验函数。
- `common/file_io.py`：`ReadErrorKind`、`ResolvedPath`、`TextReadResult`、`FileSnapshot`、`CheckContext`。2.3.2 类图中的 `FileSnapshot` 是概念视图，代码归属以本节为准。
- `common/config.py`：`RuleConfig`、`PatternSpec`、`ConfigBuildResult`、`DEFAULT_CONFIG`。
- 模块局部公开结构：`link_check.LinkRecord`（仅链接模块内部与测试使用，不进入 `rules/__init__.py` 导出）。

所有签名遵循 Python 3.10+；文件首行统一 `from __future__ import annotations`；禁止 `Any`，来自 JSON 或调用方的未知值一律以 `object` 接收并在边界做类型收窄。

**（3.1）`backend/app/core/rules/common/models.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from enum import Enum, IntEnum

class ChangeStatus(Enum): ...
class IssueLevel(Enum): ...
class ReportStatus(Enum): ...
class ExitCode(IntEnum): ...

class ChangeEntry: ...
class UnparsedLine: ...
class Finding: ...
class FileGroup: ...
class CheckSummary: ...
class DegradedModule: ...
class CheckReport: ...
class ManifestParseResult: ...
class ModuleResult: ...

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

- `make_finding`：四个必填字段（`level`/`file_path`/`message`/`suggestion`）与稳定 `rule_id` 的唯一构造入口；构造期校验 `message` 8～200 字符、`suggestion` ≤ 300 字符、`excerpt` ≤ 60 字符。
- `merge_findings`：按 `rule_id` 聚合，超过 `max_per_rule_per_file` 时生成一条"另有 N 处同类问题"，对应 2.5.1（5）、2.5.2（2）、2.5.3（4）、2.5.4（1）。
- `empty_summary` / `build_report`：保证 spec 5.6.1 第 9 条"空结果结构完整"与 2.3.2（4）统计不变量。
- `validate_report`：返回中文不变量错误列表，空元组表示通过；仅供 `engine` 内部校验，不抛异常。

**（3.2）`backend/app/core/rules/common/config.py`**

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from re import Pattern

@dataclass(frozen=True, slots=True)
class RuleConfig: ...  # 字段与默认值见 2.8.1

@dataclass(frozen=True, slots=True)
class PatternSpec:
    rule_id: str
    pattern: Pattern[str]
    level: IssueLevel
    message: str
    suggestion: str
    language: str = "any"      # "python" | "c" | "any"
    exemptable: bool = True

@dataclass(frozen=True, slots=True)
class ConfigBuildResult:
    config: RuleConfig
    warnings: tuple[str, ...] = ()

DEFAULT_CONFIG: RuleConfig

def default_config() -> RuleConfig: ...

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

- `build_config` 是 `engine` 唯一使用的配置合并入口，优先级与回退策略见 2.8.2；返回的 `warnings` 必须原样并入 `CheckReport.warnings`。
- `PatternSpec.pattern` 必须为已编译正则（`re.Pattern[str]`），避免运行期重复编译；`language` 取 `python`/`c`/`any`，由 `code_scan` 选择。
- `RuleConfig` 字段只读；模块不得构造或修改配置，只能使用 `ctx.config`。

**（3.3）`backend/app/core/rules/common/manifest.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

class ManifestReadError(Exception): ...

def parse_manifest(manifest_text: str) -> ManifestParseResult: ...

def parse_manifest_line(
    line: str,
    line_no: int,
) -> ChangeEntry | UnparsedLine | None: ...

def normalize_path(raw_path: str) -> str: ...

def has_escaping_segments(normalized_path: str) -> bool: ...

def merge_entries(entries: Sequence[ChangeEntry]) -> tuple[ChangeEntry, ...]: ...

def load_manifest_text(manifest_path: str | Path) -> str: ...
```

- `parse_manifest_line` 返回 `None` 表示空行/`#` 注释行；返回 `UnparsedLine` 表示非法行；返回 `ChangeEntry` 表示合法条目。
- `normalize_path` 只做字符串归一化（去 `./`、`\`→`/`、折叠分隔符），不做 `realpath`/`stat`；文件系统级沙箱在 `file_io.resolve_repo_path`。
- `has_escaping_segments` 仅判断归一化后是否仍含 `..` 段；绝对路径/盘符/UNC 判断在沙箱入口完成。
- `load_manifest_text` 失败时抛 `ManifestReadError`，由 `engine.run_check_file` 捕获并转为 `ReportStatus.INPUT_ERROR`；不得把异常对象放入报告。
- `merge_entries` 以归一化路径为键，状态取最后一次出现，`duplicate_count` 累加，`line_no` 保留首次出现行号。

**（3.4）`backend/app/core/rules/common/file_io.py`**

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class ReadErrorKind(Enum): ...

@dataclass(frozen=True, slots=True)
class ResolvedPath:
    relative_path: str
    absolute_path: Path | None
    is_safe: bool
    error_kind: ReadErrorKind

@dataclass(frozen=True, slots=True)
class TextReadResult:
    text: str | None
    error_kind: ReadErrorKind
    error_message: str | None

@dataclass(frozen=True, slots=True)
class CheckContext:
    repo_root: Path
    config: RuleConfig
    module_name: str
    snapshot: Callable[[str], FileSnapshot]

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

def resolve_repo_path(
    repo_root: str | Path,
    relative_path: str,
) -> ResolvedPath: ...

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

- `resolve_repo_path` 是唯一允许把清单相对路径映射为绝对路径的入口；非法路径返回 `is_safe=False` 且 `absolute_path=None`，调用方不得再触发 `stat`/`open`。
- `create_snapshot` 按路径缓存同一个 `FileSnapshot` 实例；`engine` 为 A/M 条目创建，D 条目**不得**调用。
- `FileSnapshot.text()` 首次调用读取并缓存，UTF-8（去 BOM）失败回退 GB18030；失败返回 `TextReadResult(text=None, error_kind=...)`，不抛异常。
- `read_text_from_disk` 只接受已通过沙箱的绝对路径，供 `FileSnapshot` 与清单读取复用；只使用 `r`/`rb` 模式。
- `is_binary_file` 先按扩展名黑名单，再读首 `sample_size` 字节检测 `\x00`；不读取完整文件。
- `CheckContext` 由 `engine` 构造并注入四模块；模块**不能**自行构造 `CheckContext` 或替换 `snapshot`。

**（3.5）`backend/app/core/rules/common/report.py`**

```python
from __future__ import annotations

def render_text(report: CheckReport) -> str: ...

def report_to_dict(report: CheckReport) -> dict[str, object]: ...

def report_to_json(report: CheckReport) -> str: ...
```

- 三个函数只读 `CheckReport`，不得修改原对象、不得写文件、不得发网络请求。
- `report_to_json` 使用 `json.dumps(..., ensure_ascii=False, indent=2)`；失败时回退到四必填字段最小结构并返回可解析 JSON，同时在调用方 `engine` 侧记录一条降级说明（spec 5.6.3 第 5 条）。

#### （4）四个检查模块与汇总入口的公开签名

**（4.1）`backend/app/core/rules/naming.py`**

```python
from __future__ import annotations

def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def check_naming(path: str, config: RuleConfig) -> tuple[Finding, ...]: ...

def check_directory(path: str, config: RuleConfig) -> tuple[Finding, ...]: ...

def suggest_file_name(file_name: str) -> str: ...

def suggest_directory(path: str, config: RuleConfig) -> str | None: ...

def is_test_file(path: str) -> bool: ...
```

- `check`：模块 SPI 实现，组合 `check_naming` 与 `check_directory`，执行同类合并后返回 `ModuleResult`；A/M/D 均执行，**不得**调用 `ctx.snapshot()`。
- `check_naming`：产出 `naming-001`～`naming-004`；`line_no` 固定为 `None`（文件级问题）。
- `check_directory`：产出 `naming-005`（必须修改，硬错误优先）与 `naming-006`（优化建议）。
- `suggest_file_name`：返回可直接采用的推荐文件名（如 `uart_demo_v2.c`），不得返回空串。
- `suggest_directory`：返回推荐目标目录（如 `lab/uart/`）；扩展名未命中映射表时返回 `None`。
- `is_test_file`：按 `test_*.py`、`*_test.py`、路径段 `tests/` 识别，供 `naming-005` 第③条使用。

**（4.2）`backend/app/core/rules/code_scan.py`**

```python
from __future__ import annotations

def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def detect_language(path: str) -> str: ...  # "python" | "c" | "none"

def build_code_view(text: str, language: str) -> str: ...

def scan_python_source(
    text: str,
    file_path: str,
    config: RuleConfig,
    *,
    downgrade_level: bool = False,
) -> tuple[Finding, ...]: ...

def scan_c_source(
    text: str,
    file_path: str,
    config: RuleConfig,
    *,
    downgrade_level: bool = False,
) -> tuple[Finding, ...]: ...
```

- `check`：模块 SPI 实现；仅处理 A/M 的 `.py`/`.c`/`.h`；负责二进制/编码失败跳过、> 5 MB 时产出 `code-008`、`.h` 结果降级、同规则聚合。
- `detect_language`：`.py` → `python`；`.c`/`.h` → `c`；其余 → `none`。
- `build_code_view`：把注释与字符串字面量替换为空格并保留换行，输出与原文等长，保证行号不偏移。
- `scan_python_source`：使用 `ast` 识别模块 docstring 与函数 docstring，在代码视图上匹配 `code-005`/`code-006`/`code-007`；`ast.parse` 失败时只保留文本匹配结果。
- `scan_c_source`：识别文件头注释、`main`/非 `static` 函数注释、`static` 短函数，匹配 `code-004`/`code-006`/`code-007`。
- `downgrade_level=True`：把全部"必须修改"降为"优化建议"，仅用于 `.h`（spec 5.3 引言）。

**（4.3）`backend/app/core/rules/link_check.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class LinkRecord:
    line_no: int
    raw: str
    target: str
    kind: str                     # "inline" | "image" | "reference" | "definition" | "bare"
    text: str | None = None
    reference_id: str | None = None

def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def strip_code_blocks(text: str) -> str: ...

def extract_links(text: str) -> tuple[LinkRecord, ...]: ...

def validate_links(
    links: Sequence[LinkRecord],
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...
```

- `check`：模块 SPI 实现；仅处理 A/M 的 `.md`；负责编码失败跳过、> 200 条链接时追加 `link-008`、同规则聚合。
- `strip_code_blocks`：剔除围栏代码块与行内代码，保留原行号对应的空行占位。
- `extract_links`：提取行内、图片、引用式、定义式与裸链接；`raw` 为原始片段（后续截断至 ≤ 60 字符写入 `excerpt`）。
- `validate_links`：产出 `link-001`～`link-007`，每条 `Finding.line_no` 必须来自 `LinkRecord.line_no`；不读取目标、不联网。

**（4.4）`backend/app/core/rules/sensitive.py`**

```python
from __future__ import annotations

def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult: ...

def check_file_size(
    size_bytes: int,
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...

def scan_secrets(
    text: str,
    file_path: str,
    config: RuleConfig,
) -> tuple[Finding, ...]: ...

def mask_secret(value: str) -> str: ...

def is_placeholder_context(
    line: str,
    start: int,
    end: int,
    config: RuleConfig,
) -> bool: ...
```

- `check`：模块 SPI 实现；仅处理 A/M；负责 `stat` 体积、二进制判定、文本扫描、教学豁免、脱敏与同规则聚合；D 状态直接返回空结果且不 `stat`。
- `check_file_size`：`> large_file_fail_mb` → `sens-002`（必须修改）；`> large_file_warn_mb` 且未超失败阈值 → `sens-001`（优化建议）。
- `scan_secrets`：产出 `sens-003`～`sens-007`；命中行号取首次出现行，`excerpt` 必须已脱敏。
- `mask_secret`：返回前 4 字符 + `****`；长度 ≤ 4 时返回 `****`；禁止返回原文。
- `is_placeholder_context`：判断 `[start, end)` 命中位置前后 80 字符是否包含 `placeholder_context_words`，用于 `sens-004`/`sens-005`/`sens-006` 降级；`sens-003` 与已知真实令牌不得调用本函数豁免。

**（4.5）`backend/app/core/rules/engine.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

def run_check(
    manifest_text: str,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...

def run_check_file(
    manifest_path: str | Path,
    repo_root: str | Path,
    config: RuleConfig | None = None,
) -> CheckReport: ...

def build_arg_parser() -> argparse.ArgumentParser: ...

def main(argv: Sequence[str] | None = None) -> int: ...

def exit_code_for(report: CheckReport) -> ExitCode: ...
```

- `run_check`：唯一编程入口；完成 P0～P10 全流程，返回 `CheckReport`；任何业务异常转为报告字段，不向调用方抛出。
- `run_check_file`：读取清单文件后委托 `run_check`；`ManifestReadError` 转为 `ReportStatus.INPUT_ERROR`，`warnings` 写入中文原因，`summary` 全零。
- `build_arg_parser`：构造 CLI 参数解析器，参数表见（4.7）。
- `main`：CLI 入口，返回退出码整数值；`argv=None` 时读取 `sys.argv[1:]`；模块底部以 `if __name__ == "__main__": raise SystemExit(main())` 保证 `python -m app.core.rules.engine` 可运行。
- `exit_code_for`：按 2.7.2 优先级 `2 > 3 > 1 > 0` 计算 `ExitCode`；`main` 必须使用该函数，禁止另写一套判断。

**（4.6）`backend/app/core/rules/__init__.py` 导出表**

```python
from __future__ import annotations

__all__: tuple[str, ...] = (
    "run_check",
    "run_check_file",
    "render_text",
    "report_to_dict",
    "report_to_json",
    "CheckReport",
    "CheckSummary",
    "FileGroup",
    "Finding",
    "ChangeEntry",
    "IssueLevel",
    "ReportStatus",
    "ExitCode",
    "RuleConfig",
    "DEFAULT_CONFIG",
)
```

- 该文件只允许 `from app.core.rules.engine import ...` 与 `from app.core.rules.common... import ...`，不得包含任何判定逻辑或模块级可变状态。
- 2.2.2（1）示例中的 `from app.core.rules import run_check, render_text, report_to_json` 保持不变；`render_text` 等渲染函数的**实现**在 `common/report.py`，通过本文件再导出。
- `common/*` 内部函数不在此导出；调用方不得依赖 `common` 包路径。

**（4.7）函数、`rule_id` 与数据结构对应关系**

| 公开函数 | 产出对象/字段 | `rule_id` | 关键字段约束 | 报告落点 |
|---------|--------------|-----------|-------------|---------|
| `naming.check` → `check_naming` | `ModuleResult.findings` | `naming-001`～`naming-004` | 001/002 必须修改；003/004 优化建议；`line_no=None`；`excerpt` 可为文件名 | `FileGroup.findings` |
| `naming.check` → `check_directory` | `ModuleResult.findings` | `naming-005`/`naming-006` | 005 必须修改、006 优化建议；`line_no=None`；`suggestion` 必含目标路径 | `FileGroup.findings` |
| `code_scan.check` → `scan_python_source` | `ModuleResult.findings` | `code-001`～`code-003`、`code-005`～`code-007` | 001/003/007 优化建议；002/005/006 必须修改；002～007 必带 `line_no` | `FileGroup.findings` |
| `code_scan.check` → `scan_c_source` | `ModuleResult.findings` | `code-001`～`code-004`、`code-006`、`code-007` | 001/003/007 优化建议；002/004/006 必须修改；`.h` 全部降为优化建议 | `FileGroup.findings` |
| `code_scan.check`（文件级） | `ModuleResult.findings` | `code-008` | 优化建议；`line_no` 允许 `None`；不重复报注释类问题 | `FileGroup.findings` |
| `link_check.check` → `validate_links` | `ModuleResult.findings` | `link-001`～`link-007` | 001/002/003/005 必须修改；004/006/007 优化建议；全部必带 `line_no`；`excerpt` ≤ 60 | `FileGroup.findings` |
| `link_check.check`（文件级） | `ModuleResult.findings` | `link-008` | 优化建议；`line_no` 允许 `None`；每文件最多 1 条 | `FileGroup.findings` |
| `sensitive.check` → `check_file_size` | `ModuleResult.findings` | `sens-001`/`sens-002` | 001 优化建议、002 必须修改；`line_no=None`；`excerpt=None` | `FileGroup.findings` |
| `sensitive.check` → `scan_secrets` | `ModuleResult.findings` | `sens-003`～`sens-007` | 003/004/005 必须修改（004/005 可豁免降级）；006/007 优化建议；`line_no=首次命中行`；`excerpt` 脱敏 | `FileGroup.findings` |
| `engine.run_check` / `run_check_file` | `CheckReport` | 汇总全部 | `CheckSummary` 七项统计、`files` 分组、`unparsed_lines`、`degraded_modules`、`warnings` | 根对象 |
| `report.render_text` / `report_to_dict` / `report_to_json` | 渲染结果 | 不新增 | 只读 `CheckReport`；不改字段、不重排 | 输出层 |

> **`Finding` 与 `CheckReport` 的关系**：四模块只产出 `Finding`；`engine` 按路径聚合为 `FileGroup`，再构造 `CheckSummary` 与 `CheckReport`；`report.py` 只做渲染。任何模块不得直接构造 `CheckReport`，任何渲染函数不得参与判定。

**（4.8）`engine.py` CLI 参数签名**

```text
python -m app.core.rules.engine --manifest <清单路径|-> --repo <仓库根>
                                [--format text|json] [--output <文件路径>]
                                [--config <JSON 配置路径>] [--debug]
```

| 参数 | `dest` | 类型/取值 | 必填 | 默认 | 语义 |
|------|--------|----------|------|------|------|
| `--manifest` | `manifest` | `str`，文件路径或 `-` | 是 | — | `-` 表示从 stdin 读取清单 |
| `--repo` | `repo` | `str` | 否 | `"."` | 被检查仓库根；`run_check` 内做存在性与目录校验 |
| `--format` | `format` | `"text"` / `"json"` | 否 | `"text"` | 输出载体；`json` 使用 `report_to_json` |
| `--output` | `output` | `str` / `None` | 否 | `None` | 显式指定时写 JSON 到该路径；默认只写 stdout |
| `--config` | `config` | `str` / `None` | 否 | `None` | JSON 配置文件路径；非法值回退默认并写入 `warnings` |
| `--debug` | `debug` | `bool`（`store_true`） | 否 | `False` | 仅此模式向 stderr 输出调试堆栈；正常模式禁止英文堆栈 |

- `--manifest` 的 `-` 与 `--repo` 的默认值 `"."` 由 `main` 解析后传入 `run_check` / `run_check_file`。
- 退出码由 `exit_code_for(report)` 统一计算，与 2.7.2 表一致：`0/1/2/3`。
- `build_arg_parser` 只负责参数定义，不执行检查；`main` 负责读取、调用、渲染与返回退出码。

### 2.4.4 文件间导入依赖方向

**总方向（单向，禁止反向）**：

```text
rules/__init__.py（门面，仅再导出）
        │
        ▼
engine.py（唯一汇总入口）
        │
        ├──► naming.py
        ├──► code_scan.py
        ├──► link_check.py
        ├──► sensitive.py
        └──► common/manifest.py、common/file_io.py、common/report.py、common/config.py、common/models.py

四个检查模块 ──► common/models.py、common/file_io.py
                 └─（仅 TYPE_CHECKING）──► common/config.py

common/file_io.py ──► common/config.py ──► common/models.py
common/manifest.py ──► common/models.py
common/report.py   ──► common/models.py
common/models.py   ──► 仅标准库（叶子节点）
```

```plantuml
@startuml
skinparam componentStyle rectangle
skinparam defaultFontName "Microsoft YaHei"

package "app.core.rules" {
  [__init__.py\n仅再导出] as Init
  [engine.py\n汇总入口] as Engine
  [naming.py] as Naming
  [code_scan.py] as Code
  [link_check.py] as Link
  [sensitive.py] as Sensitive
  package "common" {
    [manifest.py] as Manifest
    [file_io.py] as IO
    [config.py] as Config
    [models.py] as Models
    [report.py] as Report
  }
}

Init --> Engine
Engine --> Naming
Engine --> Code
Engine --> Link
Engine --> Sensitive
Engine --> Manifest
Engine --> IO
Engine --> Config
Engine --> Report
Engine --> Models
Naming --> Models
Naming --> IO
Code --> Models
Code --> IO
Link --> Models
Link --> IO
Sensitive --> Models
Sensitive --> IO
Naming ..> Config : 仅类型
Code ..> Config : 仅类型
Link ..> Config : 仅类型
Sensitive ..> Config : 仅类型
IO --> Config
Config --> Models
Manifest --> Models
Report --> Models
@enduml
```

| 文件 | 允许的模块级导入 | 仅类型导入（`TYPE_CHECKING`） | 禁止导入 |
|------|-----------------|------------------------------|---------|
| `rules/__init__.py` | `engine.py`、`common.models`、`common.config`、`common.report` | — | 四模块私有函数、`common.manifest`/`common.file_io` 内部实现 |
| `engine.py` | 四个检查模块、`common.models`、`common.config`、`common.manifest`、`common.file_io`、`common.report`、`argparse`/`json`/`pathlib`/`sys`/`os` | — | `app.api`、`app.db`、`app.models`、`app.services`、任何第三方包 |
| `naming.py` | `common.models`、`common.file_io`、标准库 `re`/`unicodedata` | `common.config.RuleConfig` | `engine.py`、其余三个检查模块、`common.report` |
| `code_scan.py` | `common.models`、`common.file_io`、标准库 `ast`/`re`/`time` | `common.config.RuleConfig` | `engine.py`、其余三个检查模块、`common.report` |
| `link_check.py` | `common.models`、`common.file_io`、标准库 `re`/`ipaddress` | `common.config.RuleConfig` | `engine.py`、其余三个检查模块、`common.report` |
| `sensitive.py` | `common.models`、`common.file_io`、标准库 `re`/`time`/`math` | `common.config.RuleConfig` | `engine.py`、其余三个检查模块、`common.report` |
| `common/models.py` | 仅标准库 `dataclasses`/`enum`/`re`/`collections.abc`/`typing` | — | 任何 `app.core.rules` 内其他文件、任何 I/O |
| `common/config.py` | `common.models`、标准库 `re`/`json`/`pathlib` | — | `common.file_io`、`engine`、四模块 |
| `common/manifest.py` | `common.models`、标准库 `re`/`pathlib` | — | `common.file_io`、`engine`、四模块 |
| `common/file_io.py` | `common.models`、`common.config`、标准库 `os`/`pathlib`/`codecs`/`time` | — | `engine`、四模块、`common.report` |
| `common/report.py` | `common.models`、标准库 `json` | — | `engine`、四模块、`common.file_io`/`common.manifest` |

**禁止反向导入的硬规则**：

1. `common/**` 内不得出现 `from app.core.rules.engine import ...`、`from app.core.rules.naming import ...` 等对上层或同级业务模块的导入。
2. 四个检查模块彼此**零依赖**，只能由 `engine` 串联；禁止 `naming → code_scan`、`link_check → sensitive` 等任意横向导入。
3. 四个检查模块不得导入 `engine`，也不得导入 `app.core.rules` 包根（避免循环与门面反向依赖）。
4. `engine` 不得导入 `app.core.rules` 包根；`python -m app.core.rules.engine` 运行时，`engine` 只直接导入 `common.*` 与四个兄弟模块。
5. `common` 内部保持单向：`models` 为叶子；`file_io → config → models` 合法，`config → file_io` 非法；`manifest`、`report` 只依赖 `models`。
6. 禁止导入 `app.api`、`app.db`、`app.models`、`app.services`；禁止任何第三方包。
7. `rules/__init__.py` 是唯一允许同时引用 `engine` 与 `common` 的门面文件，且不得被 `engine` 导入。

**合法/非法导入示例**：

```python
# 合法：模块只依赖 common
from app.core.rules.common.models import Finding
from app.core.rules.common.file_io import CheckContext

# 合法：engine 依赖模块与 common
from app.core.rules.naming import check as check_naming
from app.core.rules.common.manifest import parse_manifest

# 非法：common 反向依赖模块
from app.core.rules.naming import check          # 禁止

# 非法：模块反向依赖 engine
from app.core.rules.engine import run_check      # 禁止

# 非法：模块横向依赖另一模块
from app.core.rules.link_check import check      # 在 code_scan 中禁止
```

**检测方式**：实现阶段增加 `test_engine.test_import_direction`，使用标准库 `ast` 扫描 `backend/app/` 下全部产品 `.py` 的 `Import`/`ImportFrom` 节点，断言不存在上述非法边；该测试不依赖第三方静态分析工具。

### 2.4.5 与 2.2 接口设计的口径统一

> 2.2 的**参数顺序、语义、稳定性等级**全部继续有效；本节只统一"实现文件归属"与"完整类型注解"。若 2.2 与本节存在表述差异，以本节为权威口径；2.2 不再单独维护重复签名。

| 编号 | 2.2 既有表述 | 本次权威口径 | 统一后结论 | 对调用方影响 |
|------|-------------|-------------|-----------|-------------|
| C1 | `run_check()` / `run_check_file()` 列为公共 API，未标注实现文件 | 实现于 `backend/app/core/rules/engine.py`，由 `rules/__init__.py` 再导出 | 调用路径 `from app.core.rules import run_check` 不变 | 无 |
| C2 | `render_text()` / `report_to_dict()` / `report_to_json()` 列为公共 API，未标注实现文件 | 实现于 `backend/app/core/rules/common/report.py`，由 `rules/__init__.py` 再导出 | 调用路径不变；实现文件固定，避免与判定逻辑混放 | 无 |
| C3 | `parse_manifest(manifest_text: str) -> ManifestParseResult` | 实现于 `common/manifest.py`；新增 `parse_manifest_line`、`normalize_path`、`has_escaping_segments`、`merge_entries`、`load_manifest_text` 为公开辅助 | 原签名与返回类型不变；辅助函数只服务于解析与测试 | 无 |
| C4 | 模块 SPI 写作 `check(entry, ctx) -> ModuleResult` | 四个模块同名同签名；`ctx` 明确为 `common/file_io.CheckContext` | 四模块统一契约，`ModuleResult` 字段不变 | 无 |
| C5 | CLI 写作 `main(argv) -> int` | 实现于 `engine.py`；新增 `build_arg_parser() -> argparse.ArgumentParser`、`exit_code_for(report: CheckReport) -> ExitCode` | `main` 签名不变；退出码计算集中到 `exit_code_for` | 无 |
| C6 | 公共 API 列出 `RuleConfig` 及默认配置 | 实现于 `common/config.py`；新增 `build_config`、`config_from_mapping`、`load_config_file`、`PatternSpec`、`ConfigBuildResult` | `RuleConfig` 字段只增不改；新增函数为可选扩展 | 无 |
| C7 | 2.4.2 规则层允许导入未列 `common.config` | 四个模块允许 **仅类型导入** `RuleConfig`；运行期配置一律通过 `ctx.config` | 不新增运行期依赖，不形成反向边 | 无 |
| C8 | 2.3.2 类图包含 `FileSnapshot` | `FileSnapshot`、`TextReadResult`、`ReadErrorKind`、`ResolvedPath`、`CheckContext` 的实现归属为 `common/file_io.py` | 2.3.2 视为概念视图；代码归属以本节为准 | 无 |
| C9 | 2.7.2 定义 `ExitCode` 取值但未指定计算函数 | `engine.exit_code_for(report)` 为唯一计算入口，优先级 `2 > 3 > 1 > 0` | CLI、CI、后续 Web 服务共用同一退出码语义 | 无 |
| C10 | 2.2.2 调用示例 `from app.core.rules import run_check, render_text, report_to_json` | `rules/__init__.py` 的 `__all__` 必须包含这三个符号及 `CheckReport`、`RuleConfig` 等 | 示例可原样运行；不得要求调用方深入 `common` 路径 | 无 |

**统一后的签名纪律**：

1. 2.2.2 参数顺序与语义冻结；后续新增能力只能追加**带默认值的可选参数**，不得改变现有参数含义。
2. 实现阶段不得新增本节未列出的公共函数；确需新增时，先修订 2.4.3（路径/签名）与 2.4.5（口径），再写代码。
3. 不新增 `Issue` 类型别名；spec 的"问题"在代码、JSON 与文档中统一为 `Finding`。
4. `common/*` 不是公共 API；调用方只能从 `app.core.rules` 导入（测试代码除外）。
5. 2.2.1 的稳定性等级表继续有效；本节新增的辅助函数默认按"实验"级管理，直到被 2.2 正式收录。

## 2.5 四模块判定逻辑

### 2.5.1 命名与目录归属检查（`naming.py`，spec 5.2）

#### （1）输入裁剪

| 输入状态 | 是否执行 | 读取文件内容 | 判定依据 |
|---------|---------|-------------|---------|
| A | 是 | 否 | 路径字符串、扩展名、目录前缀 |
| M | 是 | 否 | 同上 |
| D | 是（唯一执行的模块） | **禁止** | 同上 |
| 无扩展名 | 是 | 否 | 仅做非法字符与长度检查，跳过目录判定（spec 5.2.3 第 1 条） |
| 扩展名不在映射表 | 是 | 否 | 仅做命名类检查，不输出目录问题（spec 5.2.3 第 2 条） |

#### （2）处理步骤

1. 取 `path` 的文件名部分与目录前缀；分别去除扩展名得到 `stem`。
2. 执行硬规则：非法字符、控制字符、结尾点、超长。
3. 汇总命名风格信号：大写字母、空格、连字符、连续下划线、非 ASCII（含中文）。
4. 依据扩展名查 `directory_map`，结合路径前缀判定目录归属（硬错误优先，其次建议）。
5. 合并同类问题：命名风格最多 1 条、目录归属最多 1 条；建议文本给出可直接采用的目标名称/目标路径。
6. 生成问题时**不读取文件**，保证 D 状态零 I/O。

#### （3）规则清单

| rule_id | 级别 | 触发条件 | 修改建议要点 | 误报/边界控制 | spec |
|---------|------|---------|-------------|--------------|------|
| `naming-001` | 必须修改 | 文件名含 `< > : " \| ? *`、控制字符（U+0000–U+001F）或以 `.` 结尾 | 给出将非法字符替换为 `_` 后的推荐文件名 | 仅检查文件名，不检查目录名中的 `:`（如盘符已被沙箱拦截）；同文件只报 1 条 | 5.2.1 第 1 条 |
| `naming-002` | 必须修改 | 文件名（含扩展名）字符数 > 120 | 建议缩短至 60 字符以内，给出截断示例 | 按 Unicode 字符计数，不按字节；同文件只报 1 条 | 5.2.1 第 2 条 |
| `naming-003` | 优化建议 | 文件名含大写、空格、连字符、连续下划线或非 ASCII 非中文符号 | 推荐"小写英文 + 单下划线"，给出示例 | 与 `naming-004` 合并；同一文件最多 1 条 | 5.2.1 第 3、8 条 |
| `naming-004` | 优化建议 | 文件名或任意路径段含中文 | 建议英文或拼音 + 下划线，说明跨平台工具链/命令行/自动化脚本不便，给出完整目标路径 | **禁止**升级为必须修改；纯中文文件最多 1 条建议 | 5.2.1 第 4、10 条 |
| `naming-005` | 必须修改 | ① `.c/.h/.py` 位于 `docs/` 下；② `.md` 位于 `backend/`、`src/`、`lab/` 下；③ 测试文件（`test_*.py`、`*_test.py`、路径含 `tests/`）不在 `backend/tests/` 下 | 给出目标路径，如 `docs/uart_demo.c` → `lab/uart/uart_demo.c`；`.md` 在 `backend/` → `docs/` | 仅当扩展名命中映射表；目录前缀按路径段匹配，避免 `backendx/` 误判 | 5.2.1 第 5、7 条 |
| `naming-006` | 优化建议 | ① `.c/.h/.py` 直接位于仓库根；② 图片不在 `assets/` 或 `docs/assets/`；③ 实验报告类 `.md`（文件名含 `lab`+数字、`实验`、`报告`、`report`）不在 `docs/` | 给出推荐目录，如根目录 `uart_demo.c` → `lab/<module>/` | 仅建议；与 `naming-005` 合并时硬错误优先；启发式仅对文件名关键词生效 | 5.2.1 第 6、9 条 |

#### （4）默认目录映射表

| 扩展名/类型 | 允许目录前缀 | 硬错误目录 | 未命中处理 |
|------------|-------------|-----------|-----------|
| `.md` | `docs/` | `backend/`、`src/`、`lab/` | 仅命名检查 |
| `.c`、`.h` | `lab/`、`src/` | `docs/` | 仅命名检查 |
| `.py` | `backend/`、`scripts/`、`lab/` | `docs/` | 仅命名检查 |
| 图片 `.png/.jpg/.jpeg/.gif/.bmp/.webp/.svg/.ico` | `assets/`、`docs/assets/` | — | 建议归入 `assets/` |
| 测试文件（按名称识别） | `backend/tests/` | 其他任意目录 | 报必须修改 |
| 未知扩展名 `.xyz` 等 | — | — | 不输出目录问题 |

#### （5）输出与聚合

- 每文件最多 4 条：`naming-001`、`naming-002`、合并后的命名风格 1 条、合并后的目录归属 1 条。
- 合并规则：若同时命中 `naming-003` 与 `naming-004`，只输出一条，级别取"优化建议"，建议文本包含"英文/拼音 + 下划线"和完整目标路径；若同时命中 `naming-005` 与 `naming-006`，只输出 `naming-005`（必须修改优先）。
- 建议文本必须含具体示例；禁止只写"命名不规范"（spec 5.2.1 第 9 条）。

### 2.5.2 代码注释与高危写法检查（`code_scan.py`，spec 5.3）

#### （1）输入裁剪与前置

| 条件 | 行为 | 依据 |
|------|------|------|
| 状态 D | 直接返回空结果，不创建快照 | 5.1.1 第 8 条、5.3.1 第 1 条 |
| 非 `.py/.c/.h` | 直接返回空结果 | 5.3.1 第 1 条 |
| 二进制 | 跳过内容扫描，记录 `skip_reason="文件内容无法解码，已跳过代码检查"` | 5.3.3 第 1 条 |
| 编码失败 | 同上 | 4.5 第 3 条 |
| 体积 > 5 MB | 输出 `code-008` 优化建议"文件过大，已跳过代码内容检查，建议拆分"，不再做 AST/正则扫描 | 5.3.3 第 2 条 |
| `.h` | 执行同族规则，输出前将所有"必须修改"降为"优化建议" | 5.3 引言 |

#### （2）处理步骤

1. **文本预处理**：去 BOM；统一 `\n`；保留原始行数组用于定位。
2. **代码视图**：状态机把注释与字符串字面量替换为空格（保留换行符），生成与原文等长、行号一致的 `code_view`。用于高危/可疑写法匹配，避免注释、文档字符串、普通字符串误报（spec 5.3.3 第 4 条）。
3. **文件头注释**：Python 首个非空语句为模块 docstring 则满足；C 去除 BOM 与前导空行后，首个非空块为 `//` 或 `/* */` 注释则满足；否则 `code-001`（优化建议）。
4. **函数识别**：
   - Python：`ast.parse`；遍历 `FunctionDef`/`AsyncFunctionDef`，记录 `name`、`lineno`、是否类方法、是否公开（不以 `_` 开头）、`end_lineno` 计算行数、函数体第一条语句是否为字符串常量（docstring）。`ast.parse` 失败（语法不完整）→ 跳过该文件全部函数注释判定，仅保留高危/可疑扫描，并记文件级说明（spec 5.3.3 第 3 条）。
   - C：正则匹配"返回类型/指针 + 函数名 + 参数列表 + `{`"，排除关键字 `if/for/while/switch/return/sizeof/struct/union/enum/typedef`、排除行首 `#define`；识别 `static` 修饰；通过大括号计数确认函数体结束，无法配对则跳过该片段。
5. **函数注释判定**：从函数起始行向上跳过空行，若紧邻为非空注释块末尾则满足；函数体内注释不计。注释语言不限（spec 5.3.1 第 5、9 条）。
6. **高危/可疑匹配**：在 `code_view` 上按预编译正则逐行匹配，记录行号；同文件同规则聚合。
7. **输出**：按行号升序；`.h` 级别降级；每文件每 `rule_id` 最多 5 条，超出合并为 1 条"另有 N 处同类问题"。

#### （3）规则清单

| rule_id | 级别 | 触发条件 | 修改建议要点 | 边界控制 | spec |
|---------|------|---------|-------------|---------|------|
| `code-001` | 优化建议 | `.py` 无模块 docstring；`.c/.h` 开头无文件用途注释 | 给出一行中文示例"本文件：串口数据收发示例" | 文件头允许 BOM/空行；有任意开头注释块即满足 | 5.3.1 第 2 条 |
| `code-002` | 必须修改 | Python 模块级公开函数/类方法缺 docstring；C 的 `main` 与非 `static` 函数缺紧邻注释 | 补充函数用途、参数、返回值；给出注释示例 | 内部函数、`.h` 降为优化；宏包裹无法识别则跳过 | 5.3.1 第 3 条 |
| `code-003` | 优化建议 | 非公开/`static` 内部函数且函数体 ≤ 10 行，缺紧邻注释 | 建议补一行用途说明 | 行数按定义行到结束行计算；仅对可识别函数 | 5.3.1 第 4 条 |
| `code-004` | 必须修改 | C 代码视图命中 `gets(`、`strcpy(`、`strcat(`、`sprintf(`、`scanf("%s")` | 改用 `fgets(buf, sizeof buf, stdin)`、`snprintf`、`strncpy` + 手动补 `\0`、`scanf("%99s")` | 仅匹配代码视图，注释/字符串不报；`.h` 降级 | 5.3.1 第 6 条 |
| `code-005` | 必须修改 | Python 代码视图命中 `eval(` 或 `exec(` | 改用 `ast.literal_eval`、显式白名单/字典映射；说明任意代码执行风险 | 排除 `ast.literal_eval`、`model.eval()` 等误匹配（匹配函数名边界） | 5.3.1 第 6 条 |
| `code-006` | 必须修改 | 字符串拼接（`+`、f-string、`%`、`.format`）结果传入 `os.system`/`os.popen`/`subprocess(shell=True)` | 改用 `subprocess.run([...], shell=False)`；必要时 `shlex.quote` | 允许 `subprocess.run(["固定命令", 参数])` 不报 | 5.3.1 第 6 条 |
| `code-007` | 优化建议 | `while(1)`/`while(true)`/`for(;;)`；`os.system(`；`subprocess` 调用；裸 `except:`；同一函数内同一数字字面量重复 ≥3 次或 ≥4 位数字 | 说明退出条件/替代方式；嵌入式轮询场景可保留；裸 `except` 改 `except Exception as e`；魔法数字提为常量 | 注释/字符串不计；`.h` 降级；魔法数字仅函数内聚合 1 条 | 5.3.1 第 7 条 |
| `code-008` | 优化建议 | 文件 > 5 MB 或内容扫描超 300 ms/1 s 预算 | 建议拆分文件；说明"仅完成体积检查/内容检查未完成" | 仅一条说明性建议，不重复报注释类问题 | 5.3.3 第 2、4 条 |

#### （4）行号与误报控制

- 代码视图替换字符为空格而非删除，确保行列位置不变，高危命中行号 = 原始行号（spec 5.3.1 第 8 条）。
- Python docstring 通过 AST 判定，不依赖字符串/注释的文本匹配。
- C 注释识别支持 `//`、`/* ... */`、`/** ... */`；Doxygen 风格同样视为满足。
- 宏定义的函数体、`#if 0` 包裹片段无法可靠解析时直接跳过，宁可漏报不误报（spec 5.3.3 第 3 条）。
- 禁止对缩进宽度、行长、变量命名大小写做必须修改判定（spec 5.3.1 第 10 条）。

### 2.5.3 Markdown 链接格式检查（`link_check.py`，spec 5.4）

#### （1）输入裁剪与预处理

| 条件 | 行为 |
|------|------|
| 状态 D 或非 `.md` | 返回空结果 |
| 二进制/编码失败 | 跳过，记录 `skip_reason="Markdown 内容无法解码，已跳过链接检查"` |
| 围栏代码块 | 识别 ``` 与 ~~~；闭合标记字符相同且长度 ≥ 开启长度；块内全部行跳过（spec 5.4.1 第 11 条） |
| 行内代码 | 剔除反引号包裹的片段，避免把示例语法当链接 |
| 引用定义 | 先全文件扫描 `[标识]: 目标` 收集定义表，再解析引用，保证顺序无关 |
| 链接总数 > 200 | 继续检查，同类格式问题按文件聚合，附加 `link-008` 说明（spec 5.4.3 第 4 条） |

#### （2）提取与校验步骤

1. 逐行提取行内链接 `[文本](目标 "可选标题")`、图片 `![说明](目标)`、引用式 `[文本][标识]`/`[标识][]`、裸链接 `https?://...`。
2. 对每个行内链接做括号配对：从 `[` 找匹配 `]`，紧接 `(` 后按成对括号找匹配 `)`；目标内允许成对括号（如维基链接）。
3. 校验目标：空/纯空白 → `link-001`；缺少闭合 → `link-002`；引用标识无定义 → `link-003`；目标含空格且未用 `<...>` 包裹 → `link-005`。
4. 校验协作适配：盘符、`file:///`、本机用户目录 → `link-004`；`http://`、`localhost`、内网 IP、空链接文本 → `link-006`；中文未编码、`../` 越出仓库 → `link-007`。
5. 不检查链接可达性、不发起网络请求、不判断 404；锚点 `#...` 与 URL 编码字符正常接受（spec 5.4.1 第 9、11 条）。
6. 每条问题带行号，`excerpt` 截取链接原文 ≤ 60 字符（spec 5.4.1 第 10 条）。

#### （3）规则清单

| rule_id | 级别 | 触发条件 | 修改建议要点 | 边界控制 | spec |
|---------|------|---------|-------------|---------|------|
| `link-001` | 必须修改 | 目标为空或仅含空白，如 `[说明]()` | 补全目标路径，或删除该链接 | 代码块内不检查 | 5.4.1 第 3 条 |
| `link-002` | 必须修改 | `]`/`)` 缺失或嵌套错乱导致结构不成立，如 `[说明](./lab03.md` | 标注缺失的右括号位置，建议合并为一行 | 合法的跨行续行不报 | 5.4.1 第 4 条、5.4.3 第 2 条 |
| `link-003` | 必须修改 | `[文本][标识]`/`[标识][]` 的标识在全文件无定义 | 补充 `[标识]: 目标` 或改为行内链接 | 快捷式 `[标识]` 仅在存在定义时视为链接，不误报 | 5.4.1 第 5 条 |
| `link-004` | 优化建议 | 目标为盘符（`C:/...`）、`file:///`、含 `C:/Users/<用户>` | 改为仓库内相对路径，给出 `./lab03.md` 示例 | 仅建议；不读取目标 | 5.4.1 第 6 条 |
| `link-005` | 必须修改 | 目标含空格且未被 `<...>` 包裹 | 改为 `%20` 编码或 `<lab 03.md>` 包裹 | `<...>` 内空格合法，不报 | 5.4.1 第 7 条 |
| `link-006` | 优化建议 | `http://` 明文协议、`localhost`/`127.0.0.1`/内网 IP、链接文本为空 | 优先 https；内网地址改为公开说明或相对路径；补充链接文本 | 每文件同类合并 1 条 | 5.4.1 第 8 条 |
| `link-007` | 优化建议 | 目标含未编码中文；或 `../` 解析后越出仓库根 | 中文建议 URL 编码；仓库外目标说明"协作环境中可能失效" | 中文最多 1 条/文件；锚点中文不报（spec 5.4.1 第 9 条） | 5.4.1 第 9 条、5.4.3 第 3 条 |
| `link-008` | 优化建议 | 单文件链接数 > 200 | 输出"该文件共 N 条链接，其中 M 条存在格式问题"，建议拆分文档 | 仅 1 条说明，不再逐条重复 | 5.4.3 第 4 条 |

#### （4）输出与聚合

- 同一行同一链接只报级别最高的一条（必须修改优先于优化建议），避免同一处重复。
- 同文件同 `rule_id` 的优化建议超过 5 条时，合并为 1 条"另有 N 处同类问题"，保留前 5 条行号。
- 行号从 1 开始；代码块剔除后用"原行号数组"定位，禁止因剔除导致行号偏移。

### 2.5.4 敏感信息与大文件检查（`sensitive.py`，spec 5.5）

#### （1）处理顺序

1. **状态 D**：直接返回空结果，不 `stat`、不读取（spec 5.5.1 第 4 条）。
2. **体积**：一次 `stat`，按字节比较。> 5 MB → `sens-002`（必须修改）；> 1 MB 且 ≤ 5 MB → `sens-001`（优化建议）。
3. **二进制判定**：扩展名命中图片/音视频/压缩包/可执行/办公文档列表，或前 8 KB 含 `\x00` → 仅保留体积结论，禁止文本匹配（spec 5.5.1 第 3 条）。
4. **文本扫描**：按行匹配凭据特征；大文本分块 + 1 s 预算。
5. **教学豁免**：对 `sens-004`/`sens-005`/`sens-006` 的匹配，若前后 80 字符含"示例/占位/demo/example/sample/mock/xxxx"→ 降为优化建议；`sens-003`（PEM 私钥）与已知真实令牌格式**不豁免**（spec 5.5.1 第 8 条）。
6. **脱敏**：保留前 4 个字符 + 固定 `****`；长度 ≤ 4 时整体 `****`；`message`、`suggestion`、`excerpt` 全部使用脱敏值（spec 5.5.1 第 9 条）。
7. **聚合**：同文件同 `rule_id` 合并为 1 条，列出前 3 个行号，其余显示"共 N 处"（spec 5.5.3 第 2 条）。

#### （2）规则清单

| rule_id | 级别 | 触发条件 | 修改建议要点 | 边界控制 | spec |
|---------|------|---------|-------------|---------|------|
| `sens-001` | 优化建议 | 文件体积 > 1 MB 且 ≤ 5 MB | 压缩/拆分，或使用 Git LFS；说明大文件入库对克隆速度的影响 | 二进制同样适用；D 状态不报 | 5.5.1 第 1 条 |
| `sens-002` | 必须修改 | 文件体积 > 5 MB | 移出仓库、改用外部存储链接或 Git LFS；附当前体积（MB，保留 1 位小数） | 二进制同样适用；D 状态不报 | 5.5.1 第 2 条 |
| `sens-003` | 必须修改 | 命中 PEM 私钥头：`-----BEGIN (RSA \|EC \|DSA \|OPENSSH \|PGP )?PRIVATE KEY-----` | 立即移除私钥并轮换凭据；改为环境变量或密钥管理服务 | **不适用教学豁免**；脱敏展示 | 5.5.1 第 5 条 |
| `sens-004` | 必须修改 | 命中已知令牌：`AKIA/ASIA` + 16 位、`ghp_/gho_/ghu_/ghs_/ghr_`、`github_pat_`、`glpat-`、`xox[baprs]-`、`sk-` + 20 位以上、`AIza` + 35 位 | 立即移除并轮换；改为环境变量/配置模板占位；补充 `.gitignore` | 教学豁免可降为优化建议；**已知真实令牌不豁免**；仅在代码视图/文本行匹配，不匹配二进制 | 5.5.1 第 5 条 |
| `sens-005` | 必须修改 | ① `password/passwd/pwd/token/secret/api_key/apikey/access_key` 等字段被赋非空字面量；② 数据库连接串 `scheme://user:pass@host` | 改为环境变量（`os.getenv`/`process.env`）或配置模板占位；给出脱敏示例 | 排除空值、`${VAR}`、`os.getenv(...)`、`<...>`、`{{...}}`、`your_`、`****`、`请输入`；注释中的纯示例可降级 | 5.5.1 第 6 条 |
| `sens-006` | 优化建议 | ① 长度 ≥ 32 的高熵字符串（字符类别 ≥ 3 且香农熵 ≥ 3.5）；② 长度 ≥ 32 的十六进制串；③ 凭据类变量被赋空值/占位符 | 提示确认是否为真实凭据；若为示例请标注"示例占位" | 与 `sens-004`/`sens-005` 同时命中时以必须修改为准，不重复报；同文件合并 1 条 | 5.5.1 第 7、8 条 |
| `sens-007` | 优化建议 | 内容扫描超 1 s 预算或文件过大未完成扫描 | 提示"文件过大，仅完成体积检查"；建议拆分 | 保留体积结论；不产生凭据类误报 | 5.5.3 第 4 条 |

#### （3）默认二进制扩展名清单

`.png .jpg .jpeg .gif .bmp .webp .ico .svg .mp4 .avi .mov .mkv .flv .wmv .mp3 .wav .flac .zip .rar .7z .gz .tar .bz2 .xz .exe .dll .so .dylib .bin .iso .pdf .doc .docx .xls .xlsx .ppt .pptx .class .pyc .o .a`

> 说明：`.svg` 虽为文本格式，但按 spec 5.5.1 第 3 条"图片只按体积判定"处理，避免图片内脚本/文本造成误报；如需扫描可在配置中移除该扩展名。

#### （4）脱敏与防止二次泄露

| 要求 | 实现 |
|------|------|
| 只保留前 4 字符 | `mask_secret(value)` → `value[:4] + "****"` |
| 长度 ≤ 4 | 返回 `****`，不展示任何原字符 |
| 禁止完整回显 | 匹配到的原文只存在于局部变量，禁止进入 `message`/`suggestion`/`excerpt`/日志 |
| 禁止写入仓库 | 不写文件；`--debug` 也不输出敏感原文 |
| 禁止网络校验 | 不调用任何外部服务；正则命中即结论 |

## 2.6 汇总入口处理流程

### 2.6.1 处理阶段

| 阶段 | 名称 | 输入 | 输出 | 失败行为 | spec |
|------|------|------|------|---------|------|
| P0 | 参数校验 | `repo_root`、`config` | 已解析的仓库根、生效配置 | 根不存在/非目录 → `输入错误` 报告，退出码 2；不进入 P1 | 5.6.3 第 1 条 |
| P1 | 清单加载 | 清单文本或清单文件路径 | 原始文本 | 文件不可读/解码失败 → `输入错误`，附中文原因，退出码 2 | 5.1.3 第 2 条 |
| P2 | 逐行解析 | 原始文本 | `entries`、`unparsed_lines` | 非法行只登记不中断；空行/`#` 行忽略 | 5.1.1 第 1～6 条 |
| P3 | 路径归一化与合并 | `entries` | 去重后的 `entries` | 绝对路径/盘符/越界 `..` → 标记"非法路径"，不读文件；重复路径合并，状态取最后一次 | 5.1.1 第 4、7 条、5.1.3 第 4 条 |
| P4 | 空清单判定 | 合并后的条目 | 空报告或继续 | 无有效条目 → 全零报告 + 提示"变更清单为空…"，退出码 0 | 5.1.3 第 1 条 |
| P5 | 快照构建 | 条目路径 | `FileSnapshot` 提供器 | 逐文件惰性创建；D 状态不创建 | 4.1 第 4 条、5.1.1 第 8 条 |
| P6 | 模块调度 | 条目 + 上下文 | 各模块 `ModuleResult` | 模块异常 → `degraded_modules`，其余模块继续；单文件异常 → 文件级 `skip_reason` | 4.2 第 3 条、5.6.3 第 3 条 |
| P7 | 汇总分组 | 全部 `Finding` + 条目 | `FileGroup` 列表 | 无问题文件也保留分组（用于展示状态与跳过原因） | 5.6.1 第 2 条 |
| P8 | 排序 | 分组与问题 | 排序后的结构 | — | 5.6.1 第 5 条 |
| P9 | 统计与状态 | 全量结果 | `CheckSummary`、`ReportStatus` | 状态不变量校验失败 → 视为内部异常，降级并输出最小报告 | 5.6.1 第 4、9 条 |
| P10 | 渲染与退出码 | 报告 + 输出格式 | 文本/JSON + 退出码 | 序列化失败 → 最小结构回退 + 降级说明 | 5.6.3 第 5 条 |

### 2.6.2 模块调度规则

| 条目状态/类型 | `naming` | `code_scan` | `link_check` | `sensitive` |
|--------------|----------|-------------|--------------|-------------|
| A/M，`.py`/`.c`/`.h` | 执行 | 执行 | 跳过 | 执行（体积 + 文本） |
| A/M，`.md` | 执行 | 跳过 | 执行 | 执行（体积 + 文本） |
| A/M，其他文本 | 执行 | 跳过 | 跳过 | 执行（体积 + 文本） |
| A/M，二进制 | 执行 | 跳过 | 跳过 | 执行（仅体积） |
| D | 执行（仅路径） | 跳过 | 跳过 | 跳过 |
| A/M 但文件不存在 | 执行 | 跳过（`skip_reason`） | 跳过（`skip_reason`） | 跳过（`skip_reason`） |
| 路径越界 | 执行命名判定（仅路径字符串） | 跳过 | 跳过 | 跳过；文件分组标记"非法路径" |

> **设计决策**：路径越界条目仍参与命名判定，因为命名检查不访问文件系统，且能提示"路径写法不规范"；但内容类模块全部跳过，并在报告中显式标记"非法路径"（spec 4.3 第 3 条）。

### 2.6.3 分组与排序

1. **文件分组**：以归一化路径为唯一键；`FileGroup.status` 取合并后的最终状态；`duplicate_count` 带入分组。
2. **文件排序**：按 `file_path` 的 Unicode 码点升序（Windows/Linux 一致），不使用本地化排序。
3. **文件内问题排序**：
   - 第一键：`level`，`必须修改`=0，`优化建议`=1；
   - 第二键：`line_no` 升序，`None` 视为无穷大排在末尾；
   - 第三键：`rule_id` 字典序；
   - 第四键：`message` 字典序（兜底，保证完全确定）。
4. **降级与非法行排序**：`unparsed_lines` 按行号升序；`degraded_modules` 按固定模块顺序 `naming → code_scan → link_check → sensitive`，再按原因字典序。
5. **跳过文件计数**：同一条目既有问题又有 `skip_reason`（如文件不存在但命名有问题）时，计入 `skipped_file_count`，问题照常保留。

### 2.6.4 摘要渲染模板

终端摘要使用固定结构，避免因模块执行顺序导致文案漂移：

```text
RepoGuard 规则检查结果
本次共检查 <entry_count> 个文件变更，发现 <issue_count> 个问题：
  必须修改：<must_fix_count> 个    优化建议：<suggestion_count> 个
请先处理「必须修改」项，再根据时间采纳「优化建议」。

[必须修改] lab/uart/uart_demo.c  (M)
  - 第 <行号> 行：<问题描述>
    修改建议：<可照做的建议>
[优化建议] docs/lab03_串口通信实验.md  (A)
  - 第 <行号> 行：<问题描述>
    修改建议：<可照做的建议>

未完成检查的文件：
  - <路径>：<中文跳过原因>

模块降级说明：
  - <模块中文名>：<中文原因>（结果可能不完整）

提示：<配置回退/空清单/序列化回退等说明>
```

**渲染约束**：
- 全部中文；不输出英文堆栈、英文规则名作为主提示；`rule_id` 可在括号内附带，便于追溯。
- 先必须修改、后优化建议；同一文件内遵循 2.6.3 排序。
- 无问题时仍输出统计与"未发现问题"提示；空清单输出"变更清单为空，请确认是否已生成改动列表"。
- 降级时摘要末尾必须出现"结果可能不完整"（spec 5.6.1 第 10 条）。

### 2.6.5 JSON 输出结构

```json
{
  "status": "正常",
  "summary": {
    "entry_count": 0,
    "issue_count": 0,
    "must_fix_count": 0,
    "suggestion_count": 0,
    "skipped_file_count": 0,
    "degraded_module_count": 0,
    "unparsed_line_count": 0
  },
  "files": [
    {
      "file_path": "lab/uart/uart_demo.c",
      "status": "M",
      "duplicate_count": 1,
      "skip_reason": null,
      "findings": [
        {
          "level": "必须修改",
          "file_path": "lab/uart/uart_demo.c",
          "message": "第 27 行使用了无边界保障的 strcpy，存在缓冲区溢出风险",
          "suggestion": "改用 snprintf(buf, sizeof(buf), ...) 或带长度检查的 strncpy",
          "rule_id": "code-004",
          "line_no": 27,
          "excerpt": null
        }
      ]
    }
  ],
  "unparsed_lines": [
    { "line_no": 3, "raw": "X docs/a.md", "reason": "未知状态：X" }
  ],
  "degraded_modules": [
    { "module": "link_check", "reason": "链接检查模块执行异常，结果可能不完整" }
  ],
  "warnings": []
}
```

**序列化约束**：
- `ensure_ascii=False`；UTF-8 输出；中文、`\` 不转义（路径已归一化为 `/`）。
- 枚举输出中文值（`必须修改`/`优化建议`、`正常`/`部分降级`/`输入错误`）与单字母状态。
- 不含时间戳、绝对路径、异常对象、主机名。
- 字段名与 2.3 完全一致；`null` 表示可选字段缺失，不省略字段（空结果也保持完整骨架，spec 5.6.1 第 9 条）。
- JSON 序列化失败时，回退为仅含 `level`/`file_path`/`message`/`suggestion` 的最小结构，并在 `warnings` 记录"部分附加信息未能输出"。

## 2.7 错误处理与退出状态

### 2.7.1 统一异常策略

| 原则 | 实现 |
|------|------|
| 不向调用方抛业务异常 | `run_check*()` 顶层 `try/except Exception`，任何异常都转为 `CheckReport` |
| 不吞掉故障 | 每个异常必须进入 `degraded_modules`、`skip_reason` 或 `warnings`，附中文原因 |
| 不输出英文堆栈 | 默认仅输出中文摘要；`--debug` 才向 stderr 打印 traceback（明确标注"调试信息"） |
| 模块级隔离 | 四模块分别包裹；一个模块失败不影响其余三个 |
| 文件级隔离 | 单文件读取/解析/判定异常 → 该文件 `skip_reason`，其他文件继续 |
| 不可捕获项 | `KeyboardInterrupt`、`SystemExit`、`MemoryError` 不转为业务结果，允许进程终止 |
| 只记录一次 | 同一文件同一原因只记录一条跳过说明，避免重复计数 |

### 2.7.2 退出状态

| 退出码 | 名称 | 触发条件 | 优先级 | spec |
|--------|------|---------|--------|------|
| 0 | `OK` | 无问题、或仅有优化建议、或空清单 | 最低 | 5.6.1 第 8 条、5.1.3 第 1 条 |
| 1 | `MUST_FIX` | 至少 1 条"必须修改" | 中 | 5.6.1 第 8 条 |
| 2 | `INPUT_ERROR` | 仓库根不存在/非目录；清单整体不可读或无法解码 | **最高** | 5.6.1 第 8 条、5.6.3 第 1 条 |
| 3 | `EXECUTION_ERROR` | 至少 1 个模块降级、或报告序列化回退、或汇总内部异常 | 高（低于输入错误） | 5.6.1 第 8 条 b、5.6.3 第 3 条 |

**优先级规则**：`2 > 3 > 1 > 0`。例如同时存在"必须修改"和"链接模块降级"→ 返回 3；仓库根不存在 → 返回 2，即使清单中有必须修改内容也返回 2。

> 设计理由：spec 5.6.1 第 8 条要求"引擎自身降级或输入不可读时必须返回区别于『有问题』的独立退出状态，避免故障被误判为通过"。若降级返回 1，CI 会误以为"有业务问题但引擎正常"；返回 3 可让流水线区分"检查完成但有违规"与"检查未完整执行"。

### 2.7.3 错误场景处理清单

| 场景 | 检测点 | 处理动作 | 报告表达 | 退出码 | spec |
|------|--------|---------|---------|--------|------|
| 清单为空/仅空白/仅注释 | P2 后条目数为 0 | 返回空报告 | `warnings`："变更清单为空，请确认是否已生成改动列表"；统计全零 | 0 | 5.1.3 第 1 条 |
| 清单文件不存在/无权限 | P1 | 不进入文件检查 | `status=输入错误`；`warnings`："无法读取变更清单：<路径>，请确认文件存在且可读" | 2 | 5.1.3 第 2 条 |
| 未知状态（如 `X`） | P2 | 记入 `unparsed_lines`，继续 | 行号 + 原文 + "未知状态：X" | 不单独改变 | 5.1.1 第 2 条 |
| 只有状态缺路径 | P2 | 记入 `unparsed_lines`，不访问文件系统 | 行号 + 原文 + "缺少文件路径" | 不单独改变 | 5.1.1 第 6、10 条 |
| 路径越界/绝对路径/盘符 | P3 | 拒绝读取，标记非法路径 | 文件分组 `skip_reason`："路径超出仓库范围，已跳过：<路径>"；命名类结果保留 | 不单独改变 | 4.3 第 3 条、5.1.3 第 4 条 |
| A/M 文件不存在 | P5/P6 | 命名照常，内容模块跳过 | `skip_reason`："文件不存在，已跳过内容检查" | 不单独改变 | 5.1.3 第 3 条 |
| 编码不可识别 | 快照 `text()` | 命名照常，内容模块跳过 | `skip_reason`："文件编码无法识别，建议另存为 UTF-8 后重试" | 不单独改变 | 4.5 第 3 条、5.1.3 第 5 条 |
| 二进制文件 | 快照判定 | 仅体积检查 | 无 `skip_reason`；不产生内容类问题 | 不单独改变 | 5.5.1 第 3 条 |
| 大文件 > 5 MB | 快照体积 | 敏感模块报必须修改；代码模块报说明性建议 | `sens-002` + `code-008`（如为代码） | 1（存在必须修改） | 5.5.1 第 2 条、5.3.3 第 2 条 |
| 单文件内容扫描超时 | 模块内部计时 | 提前结束该文件扫描 | `code-008`/`sens-007` 优化建议；保留体积结论 | 不单独改变 | 5.3.3 第 4 条、5.5.3 第 4 条、4.1 第 2 条 |
| 单个模块整体异常 | P6 `try/except` | 记降级，继续其余模块 | `degraded_modules`：模块中文名 + "执行异常，结果可能不完整"；摘要提示 | 3 | 4.2 第 3 条、5.6.3 第 3 条 |
| 全部条目被跳过 | P7 后无问题且跳过数=条目数 | 空问题列表 + 跳过统计 | 摘要："本次未完成任何文件检查，请确认清单与仓库路径是否匹配" | 0 或 1（看是否有命名类必须修改） | 5.6.3 第 2 条 |
| 配置非法（阈值倒置/类型错误/未知语言） | P0 配置合并 | 回退默认值 | `warnings`："配置项 <名称> 取值非法，已使用默认值" | 不单独改变 | 6.4、4.4 第 3 条 |
| JSON 序列化失败 | P10 | 回退四必填字段最小结构 | `warnings`："部分附加信息未能输出"；记降级 | 3 | 5.6.3 第 5 条 |
| 输出路径不可写（显式 `--output`） | P10 | 保留 stdout 输出，不回滚检查结果 | `warnings`："无法写入输出文件：<路径>" | 3 | 4.3 第 5 条 |

### 2.7.4 日志与提示文案规范

1. 主要提示一律简体中文；模块名使用中文映射：`naming → 命名与目录检查`、`code_scan → 代码检查`、`link_check → 链接检查`、`sensitive → 敏感信息与大文件检查`。
2. 不打印英文异常类名作为主提示；`--debug` 模式下可附加原始异常到 stderr，并加"以下为调试信息，可忽略"。
3. 不在日志、摘要、JSON 中输出完整凭据；`excerpt` 对敏感内容始终脱敏。
4. 提示中不出现绝对路径（仓库外路径仅在"清单不可读"等必要场景出现，并按原样展示）。

## 2.8 配置项

### 2.8.1 配置模型

`RuleConfig` 为冻结 dataclass，字段全部带默认值；调用方可按关键字覆盖，也可通过 CLI `--config` 读取 JSON 后合并。模块只读配置，不得修改。

| 字段 | 类型 | 默认值 | 约束 | 用途 | spec |
|------|------|--------|------|------|------|
| `large_file_warn_mb` | `float` | `1.0` | > 0 且 < `large_file_fail_mb` | 大文件优化建议阈值 | 6.4 第 1 条 |
| `large_file_fail_mb` | `float` | `5.0` | > `large_file_warn_mb` | 大文件必须修改阈值 | 6.4 第 2 条 |
| `code_scan_max_mb` | `float` | `5.0` | > 0 | 超过则跳过代码内容扫描 | 5.3.3 第 2 条 |
| `large_text_scan_timeout_s` | `float` | `1.0` | > 0，≤ 5 | 大文本内容扫描预算 | 4.1 第 2 条、5.5.3 第 4 条 |
| `per_file_budget_ms` | `int` | `300` | > 0 | 单文件全部检查预算 | 4.1 第 2 条 |
| `link_max_per_file` | `int` | `200` | > 0 | 链接聚合阈值 | 5.4.3 第 4 条 |
| `max_findings_per_rule_per_file` | `int` | `5` | ≥ 1 | 代码/链接问题聚合阈值 | 5.6.1 第 11 条（防膨胀） |
| `directory_map` | `Mapping[str, tuple[str, ...]]` | 见 2.5.1（4） | 键为小写扩展名，值为目录前缀元组 | 目录归属判定 | 6.4 第 4 条、5.2.1 第 7 条 |
| `hard_dangerous_patterns` | `tuple[PatternSpec, ...]` | 见 2.5.2（3） | 可追加，**不得删除基础项** | 高危写法清单 | 6.4 第 5 条 |
| `suspicious_patterns` | `tuple[PatternSpec, ...]` | 见 2.5.2（3） | 可追加 | 可疑写法清单 | 5.3.1 第 7 条 |
| `secret_patterns` | `tuple[PatternSpec, ...]` | 见 2.5.4（2） | 可追加；禁止关闭私钥/真实令牌判定 | 敏感信息特征 | 6.4 第 6 条 |
| `placeholder_context_words` | `tuple[str, ...]` | `("示例","占位","demo","example","sample","mock","xxxx")` | 可追加 | 教学豁免上下文 | 5.5.1 第 8 条 |
| `binary_extensions` | `tuple[str, ...]` | 见 2.5.4（3） | 可追加/移除 `.svg` | 二进制判定 | 5.5.1 第 3 条 |
| `naming_chinese_mode` | `str` | `"仅建议"` | **固定**，仅允许"仅建议" | 中文命名口径 | 6.4 第 3 条、5.2.1 第 4 条 |
| `output_language` | `str` | `"zh-CN"` | **固定**，非法值回退并提示 | 输出语言 | 6.4 第 7 条 |

> **固定不可配置项**（即使调用方传入也拒绝并提示）：
> - 中文文件名只能给优化建议，禁止升级为必须修改；
> - PEM 私钥与已知真实令牌必须判定为必须修改；
> - 规则引擎只读、离线、不执行被扫描代码；
> - 输出语言固定简体中文；
> - 脱敏策略固定"前 4 字符 + `****`"。

### 2.8.2 配置来源与优先级

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1（最高） | 调用方直接传入的 `RuleConfig` 关键字参数 | Web/CI 进程内调用推荐方式 |
| 2 | CLI `--config <JSON>` | 文件必须是 UTF-8 JSON 对象；未知字段忽略并提示 |
| 3（最低） | `common/config.py` 内置默认值 | 保证零配置可运行 |

**合并与校验规则**：
1. 浅合并后逐字段校验类型与取值；类型错误（如字符串传给浮点字段）→ 回退默认 + `warnings`。
2. 阈值倒置（warn ≥ fail）→ 两项同时回退默认 + `warnings`，不使用"自动交换"以免掩盖错误配置。
3. `directory_map` 合并策略：调用方提供时**整体替换**默认表，避免部分覆盖导致规则碎片化；配置中必须包含 `.md`、`.c/.h`、`.py` 三项，否则回退默认并提示。
4. `hard_dangerous_patterns`/`secret_patterns` 合并策略：默认项 + 追加项；不允许通过配置删除基础项。
5. 配置 JSON 文件不可读/非对象 → 回退默认 + `warnings`，退出码不变（不影响检查执行）。
6. 配置解析不读取仓库内文件，避免把被扫描内容当配置。

### 2.8.3 配置示例

```json
{
  "large_file_warn_mb": 1.0,
  "large_file_fail_mb": 5.0,
  "per_file_budget_ms": 300,
  "link_max_per_file": 200,
  "directory_map": {
    "md": ["docs/"],
    "c": ["lab/", "src/"],
    "h": ["lab/", "src/"],
    "py": ["backend/", "scripts/", "lab/"]
  }
}
```

> 示例仅展示常用项；未出现的字段使用默认值。该 JSON 不落盘到仓库，由调用方按需提供。

## 2.9 测试策略

### 2.9.1 测试框架与原则

| 项目 | 选择 | 理由 |
|------|------|------|
| 测试框架 | 标准库 `unittest` | 与"零第三方依赖"一致；环境修复后即可运行；CI 无需安装 pytest |
| 断言风格 | `assertEqual`/`assertIn`/`assertTrue` + 表驱动 `subTest` | 规则多、用例密，表驱动可读性高 |
| 测试数据 | 临时目录工厂 + `demo-repo` 端到端样例 | 单元测试不依赖仓库真实文件；集成测试验证真实清单 |
| 隔离性 | 每个用例独立 `TemporaryDirectory`，用例结束自动清理 | 防止文件互相污染，保证可重复执行 |
| 只读验证 | 执行前后对被测文件计算 `size + sha256` 并比对 | 验证 spec 4.2 第 5 条、4.3 第 1 条 |
| 网络验证 | 测试进程内 monkeypatch `socket.socket`，任何调用即失败 | 验证 spec 4.3 第 2 条、5.4.1 第 11 条 b |
| 确定性验证 | 同一输入连续执行两次，`report_to_json()` 字符串完全相等 | 验证 spec 4.2 第 4 条、7.1 第 4 条 |

### 2.9.2 测试分层与文件职责

| 测试文件 | 层级 | 覆盖内容 | 关键用例 |
|---------|------|---------|---------|
| `test_manifest.py` | 单元 | spec 5.1.1：格式解析、状态大小写、路径归一化、空行/注释、非法行、重复合并、D 状态范围 | `A`/`M`/`D`、`a/m/d`、`.\lab\uart\uart_demo.c`、`X` 未知状态、只有状态、重复 A/M、500 字符截断、路径 `..` |
| `test_naming.py` | 单元 | spec 5.2.1 全部 10 条 + 3 个异常场景 | 中文文件名只出优化建议、`UART Demo-v2.C` → `uart_demo_v2.c`、`docs/uart_demo.c` 必须修改、根目录源码建议、无扩展名、未知扩展名、同类合并 |
| `test_code_scan.py` | 单元 | spec 5.3.1 全部 10 条 + 4 个异常场景 | `main` 缺注释、公开函数缺 docstring、8 行 static 函数只建议、`strcpy` 必须、注释/字符串中的 `strcpy` 不报、`eval`、shell 拼接、`while(1)`、裸 `except`、`.h` 降级、超 5 MB 跳过、语法异常不误报 |
| `test_link_check.py` | 单元 | spec 5.4.1 全部 11 条 + 4 个异常场景 | 空目标、缺右括号、引用缺定义、`file:///C:/...`、`./lab 03.md`、`http://`、中文锚点不报、代码块内不报、>200 条聚合、行号与原文 ≤60 |
| `test_sensitive.py` | 单元 | spec 5.5.1 全部 10 条 + 4 个异常场景 | 1 MB/5 MB 边界、二进制只报体积、PEM 私钥、`ghp_`、`password = "123456"`、连接串、40 位 hex 建议、示例占位降级、脱敏 `ghp_****`、多行聚合前 3 处、扫描超时 |
| `test_engine.py` | 集成 | spec 5.6.1 全部 11 条、5.1.3/5.6.3 异常场景、四模块协同、2.4.4 导入方向 | 空清单全零、仓库根不存在、模块异常降级、按文件分组、排序稳定性、统计一致性、状态判定、JSON 中文不转义、两次执行一致、只读校验、500 条性能基准、`test_import_direction`（AST 扫描无反向导入） |
| `test_cli.py` | 端到端 | spec 5.6.1 第 8 条、6.4、7.1 | `--format text/json`、`--output`、`--config` 非法回退、退出码 0/1/2/3、`--debug` 不泄露敏感信息 |
| `fixtures/sample_changes.txt` | 数据 | 交付物；四模块场景 + A/M/D + 注释/空行 | 见 2.10.2 |

### 2.9.3 规则覆盖矩阵（每条规则至少 1 正例 + 1 反例）

| 模块 | 规则 | 正例（应报） | 反例（不应报） |
|------|------|-------------|--------------|
| naming | naming-001 | `lab/a:b.c` | `lab/a_b.c` |
| naming | naming-002 | 121 字符文件名 | 120 字符文件名 |
| naming | naming-003 | `UART Demo-v2.C` | `uart_demo_v2.c` |
| naming | naming-004 | `docs/串口实验.md`（仅优化建议） | `docs/serial_lab.md` |
| naming | naming-005 | `docs/uart_demo.c`、`lab/readme.md` | `lab/uart/uart_demo.c`、`docs/readme.md` |
| naming | naming-006 | 根目录 `uart_demo.c` | `lab/uart/uart_demo.c` |
| code | code-001 | 无模块 docstring 的 `.py` | 首行 docstring 的 `.py` |
| code | code-002 | 无注释 `main` | `/* 串口初始化 */` 紧邻的 `main` |
| code | code-003 | 8 行 `static` 无注释（仅建议） | 8 行 `static` 有 `//` 注释 |
| code | code-004 | `strcpy(dst, src);` | 注释 `// 不要使用 strcpy` |
| code | code-005 | `eval(user_input)` | `ast.literal_eval(text)` |
| code | code-006 | `os.system("rm " + name)` | `subprocess.run(["ls"])` |
| code | code-007 | `while(1)`、裸 `except:` | `while (running)`、`except ValueError:` |
| code | code-008 | 6 MB 的 `.c` | 100 KB 的 `.c` |
| link | link-001 | `[说明]()` | `[说明](./lab03.md)` |
| link | link-002 | `[说明](./lab03.md` | `[说明](./lab03.md)` |
| link | link-003 | `[说明][ref1]` 无定义 | `[说明][ref1]` + `[ref1]: ./a.md` |
| link | link-004 | `file:///C:/Users/student/lab03.md` | `./lab03.md` |
| link | link-005 | `[说明](./lab 03.md)` | `[说明](<./lab 03.md>)` |
| link | link-006 | `http://example.com`、`[](./a.md)` | `https://example.com`、`[说明](./a.md)` |
| link | link-007 | `../outside.md`、未编码中文 | `./实验指导.md#第三部分`（仅建议/不报必须） |
| link | link-008 | 201 条链接 | 200 条链接 |
| sensitive | sens-001 | 2 MB 文件 | 900 KB 文件 |
| sensitive | sens-002 | 6 MB 文件 | 4 MB 文件 |
| sensitive | sens-003 | `BEGIN RSA PRIVATE KEY` | 文本"私钥请勿提交" |
| sensitive | sens-004 | `ghp_abcdef123456` | `ghp_****` 占位 |
| sensitive | sens-005 | `password = "123456"` | `password = os.getenv("PWD")` |
| sensitive | sens-006 | 40 位 hex | 8 位普通字符串 |
| sensitive | sens-007 | 6 MB 文本扫描超时 | 100 KB 文本正常完成 |

### 2.9.4 专项测试

| 专项 | 用例设计 | 验收目标 |
|------|---------|---------|
| 只读 | 对临时文件执行检查，比较前后 `sha256` 与 `mtime`/`size`；断言目录内文件列表不变 | spec 4.2 第 5 条、4.3 第 1、5 条 |
| 不联网 | `patch("socket.socket", side_effect=AssertionError)` 包裹 engine 执行 | spec 4.3 第 2 条、5.4.1 第 11 条 b |
| 不执行被扫描代码 | 在 `.py` 中放置 `raise RuntimeError` 与副作用文件写入语句；执行后断言副作用未发生 | spec 4.3 第 1 条、5.3.1 第 10 条 |
| 路径越界 | `../outside.md`、`C:\Windows\win.ini`、`//server/share/a.md`、符号链接指向仓库外 | spec 4.3 第 3 条、5.1.3 第 4 条 |
| 编码兼容 | UTF-8 BOM、GB18030 中文、非法字节、CRLF | spec 4.5 第 2、3、4 条 |
| 路径分隔符 | `lab\uart\uart_demo.c` 与 `lab/uart/uart_demo.c` 输出一致 | spec 4.5 第 1、5 条 |
| 确定性 | 两次执行 JSON 完全相等；打乱清单行顺序后问题集合（不含行号差异）一致 | spec 4.2 第 4 条 |
| 性能 | 生成 500 条清单、100 个可读文件；断言端到端 < 10 s（本机基准，CI 可放宽 2 倍）；单文件 < 300 ms；5 MB 文本扫描 < 1 s | spec 4.1 第 1、2、3 条 |
| 脱敏 | 断言输出中不含完整令牌、密码、私钥；只出现前 4 字符 + `****` | spec 4.3 第 4 条、5.5.1 第 9 条 |
| CLI 退出码 | 0（仅建议/空）、1（必须修改）、2（输入错误）、3（模块降级/序列化回退） | spec 5.6.1 第 8 条 |

### 2.9.5 测试执行方式

```bash
# 工作目录必须是 backend/
cd backend
python -m unittest discover -s tests -v
```

- 单个测试文件：`python -m unittest tests.test_naming -v`。
- 端到端样例：`python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo`。
- 性能基准单独运行：`python -m unittest tests.test_engine.EnginePerformanceTest -v`（默认跳过耗时长用例，使用环境变量 `RULES_PERF=1` 开启）。
- 当前环境 Python 解释器不可用（见 1.2.3）；实现阶段第一步必须验证 `python -c "import ast, dataclasses"` 可执行，否则测试无法进行。

### 2.9.6 与验收条件的对应

| spec 7.1 验收条件 | 测试证据 |
|------------------|---------|
| 第 1 条：五个文件同时存在 | `test_engine.py::test_delivery_files_exist` 断言五个路径存在且可导入 |
| 第 2 条：requirements.txt 仅依赖项/注释 | `test_engine.py::test_requirements_txt` 解析非注释行，断言为空 |
| 第 3 条：样例清单覆盖四模块输出 | `test_engine.py::test_sample_manifest_covers_all_modules` 断言四类 `rule_id` 前缀均出现（`naming-`/`code-`/`link-`/`sens-`） |
| 第 4 条：两次执行结果一致 | `test_engine.py::test_report_is_deterministic` |

## 2.10 交付物清单

### 2.10.1 交付物路径与内容

| 序号 | 路径 | 类型 | 内容要求 | 验收依据 |
|------|------|------|---------|---------|
| 1 | `backend/app/core/rules/naming.py` | Python 模块 | 实现 spec 5.2 全部业务规则；`check(entry, ctx)` 契约；问题带 `rule_id`、目标名称/目录 | spec 7 第 1 条 |
| 2 | `backend/app/core/rules/code_scan.py` | Python 模块 | 实现 spec 5.3；Python `ast` + C 正则；只读不执行；`.h` 降级 | spec 7 第 2 条 |
| 3 | `backend/app/core/rules/link_check.py` | Python 模块 | 实现 spec 5.4；代码块剔除、引用定义、行号与原文 | spec 7 第 3 条 |
| 4 | `backend/app/core/rules/sensitive.py` | Python 模块 | 实现 spec 5.5；体积分级、二进制跳过、脱敏、教学豁免 | spec 7 第 4 条 |
| 5 | `backend/app/core/rules/engine.py` | Python 模块 | 实现 spec 5.1、5.6；唯一入口、CLI、退出码；`if __name__ == "__main__"` 守卫 | spec 7 第 5 条 |
| 6 | `backend/app/core/rules/__init__.py` | 包初始化 | 只再导出公共 API，不含逻辑 | 支撑第 5 条 |
| 7 | `backend/app/core/rules/common/{__init__,models,config,manifest,file_io,report}.py` | 内部支撑包 | 数据结构、配置、解析、IO、渲染；不对外暴露 | 支撑 1～5 |
| 8 | `backend/app/__init__.py`、`backend/app/core/__init__.py` | 包标记 | 空文件或仅版本注释 | 导入可用性 |
| 9 | `backend/requirements.txt` | 依赖清单 | **零第三方依赖**；仅注释说明"Python 3.10+ 标准库即可运行"；不含多余说明 | spec 7 第 6 条、7.1 第 2 条 |
| 10 | `backend/tests/fixtures/sample_changes.txt` | 样例数据 | UTF-8 无 BOM；覆盖 A/M/D、中文名、错目录、缺注释、异常链接、大文件、疑似密钥、空行、注释行、非法行、重复路径 | spec 7 第 7 条、7.1 第 3 条 |
| 11 | `backend/tests/test_*.py` | 测试代码 | 见 2.9.2；标准库 `unittest` | spec 7.1 全部 |
| 12 | `docs/rules_engine_usage.md` | 中文说明 | 如何生成变更清单、如何调用入口、如何阅读两类级别与退出码、样例运行 | spec 7 第 8 条 |
| 13 | `demo-repo/` 最小样例文件 | 样例仓库 | 见 2.10.3；用于端到端演示，不包含真实体积的大文件 | spec 7.1 第 3 条 |

**明确不产出的内容**：
- 不修改、不新增 `frontend/`、`app/api/`、`app/db/`、`app/models/`、`app/services/` 下任何文件；
- 不新增 `pyproject.toml`、`setup.py`、`Dockerfile`、数据库迁移、CI 配置文件；
- 不向仓库写入任何检查结果、日志、缓存；
- 不提交真实大文件与真实密钥（样例中的密钥均为无效占位串）。

### 2.10.2 样例变更清单内容（写入 `backend/tests/fixtures/sample_changes.txt`）

```text
# RepoGuard 样例变更清单（UTF-8，用于本地测试）
# 状态：A=新增  M=修改  D=删除

A docs/lab03_串口通信实验.md
M lab/uart/uart_demo.c
A lab/uart/UART Demo-v2.C
A docs/uart_demo.c
A backend/app/example_config.py
M docs/lab02_broken_link.md
A assets/large_sample.mp4
D notes/old_lab02.md
A backend/tests/test_demo.py
M lab/uart/uart_demo.c
X notes/unknown_status.md
M
```

**逐条设计意图**：

| 行 | 条目 | 触发能力 | 预期结果 |
|----|------|---------|---------|
| 1-2 | 注释行 | 清单解析 | 忽略，不计入统计 |
| 3 | 空行 | 清单解析 | 忽略 |
| 4 | `A docs/lab03_串口通信实验.md` | naming-004、sensitive（体积） | 中文命名优化建议；不产生必须修改 |
| 5 | `M lab/uart/uart_demo.c` | code-001/002/004/007、sensitive | 缺文件头注释、`main` 缺注释、`strcpy`、`while(1)` |
| 6 | `A lab/uart/UART Demo-v2.C` | naming-003 | 命名风格优化建议，示例 `uart_demo_v2.c` |
| 7 | `A docs/uart_demo.c` | naming-005 | 源码放 `docs/`，必须修改，建议移入 `lab/uart/` |
| 8 | `A backend/app/example_config.py` | sensitive-004/005、code-001/002/005 | 明文密码/令牌必须修改；缺注释；可能的 `eval` |
| 9 | `M docs/lab02_broken_link.md` | link-001/002/003/004/005/006 | 空目标、缺右括号、引用缺定义、本地绝对路径、空格、`http://` |
| 10 | `A assets/large_sample.mp4` | sensitive-001/002 | 若本地放置 >1 MB 样例则报体积；未放置时按"文件不存在"跳过，属预期 |
| 11 | `D notes/old_lab02.md` | naming（仅路径） | 不读取文件、不报体积/内容问题 |
| 12 | `A backend/tests/test_demo.py` | naming-005（反例） | 位于 `backend/tests/`，不报目录错误 |
| 13 | `M lab/uart/uart_demo.c` | 重复路径合并 | 与第 5 行合并为 1 个条目，状态取 `M`，`duplicate_count=2` |
| 14 | `X notes/unknown_status.md` | 清单解析 | 记入 `unparsed_lines`，原因"未知状态：X" |
| 15 | `M`（只有状态） | 清单解析 | 记入 `unparsed_lines`，原因"缺少文件路径" |

> **大文件说明**：为避免向共享学习仓库提交数 MB 的二进制文件，`demo-repo/assets/large_sample.mp4` 默认不提交。本地验证大文件规则时，可自行生成一个 > 5 MB 的占位文件（如 `fsutil file createnew`）或由 `test_sensitive.py` 在临时目录生成；未生成时该条目显示"文件不存在，已跳过内容检查"，不影响其余四类检查输出。此约定同时保证 spec 7.1 第 3 条"正常完成解析并覆盖全部四个检查模块的问题输出"（敏感信息模块的 `sens-004/005` 仍会输出）。

### 2.10.3 配套样例文件清单（`demo-repo/`）

| 路径 | 内容要点 | 服务规则 |
|------|---------|---------|
| `demo-repo/docs/lab03_串口通信实验.md` | 正常中文实验说明，含 1 个正常相对链接 | naming-004、link 反例 |
| `demo-repo/docs/uart_demo.c` | 与 `lab/uart/uart_demo.c` 内容相同或简化 | naming-005 |
| `demo-repo/docs/lab02_broken_link.md` | 含 `[说明]()`、`[说明](./lab03.md`、`[说明][ref1]`（无定义）、`file:///C:/Users/student/lab02.md`、`[说明](./lab 02.md)`、`http://example.com` | link-001～006 |
| `demo-repo/lab/uart/uart_demo.c` | 无文件头注释；`main` 无紧邻注释；含 `strcpy` 与 `while(1)`；UTF-8 中文注释 | code-001/002/004/007 |
| `demo-repo/lab/uart/UART Demo-v2.C` | 空实现或最小 C 文件 | naming-003 |
| `demo-repo/backend/app/example_config.py` | 含 `password = "123456"`、`token = "ghp_abcdef123456"`（无效占位）、无模块 docstring | sens-004/005、code-001/002 |
| `demo-repo/backend/tests/test_demo.py` | 最小 `unittest` 用例，带模块 docstring 与函数 docstring | naming-005 反例、code 反例 |
| `demo-repo/notes/old_lab02.md` | 可不存在（D 状态不读取） | D 状态范围约束 |
| `demo-repo/assets/large_sample.mp4` | 默认不提交；本地按需生成 > 5 MB 占位 | sens-001/002 |

### 2.10.4 requirements.txt 内容策略

```text
# RepoGuard 规则引擎运行依赖
# Python >= 3.10（仅使用标准库，无第三方包）
```

- 非注释行为空，符合"只包含运行规则引擎所必需的依赖"（零依赖）。
- 不写 `pytest`、`markdown`、`pyyaml` 等开发/可选依赖；测试使用标准库 `unittest`，Markdown 使用自研轻量解析。
- 不写版本锁定文件，避免学生环境出现解析冲突。

## 2.11 与 spec.md 的可追溯映射

### 2.11.1 全局约束映射

| spec 条款 | 需求要点 | 设计落点 | 实现位置 |
|-----------|---------|---------|---------|
| 1.2 核心输入 | 清单、仓库根、可选阈值、单次触发 | `run_check*()` 参数、`RuleConfig`、CLI | `engine.py`、`common/config.py` |
| 1.3 核心输出 | 分组问题、统计、中文摘要、降级提示 | `CheckReport`、`render_text`、`warnings` | `common/models.py`、`common/report.py` |
| 1.4 职责边界 | 不修复/不 Git/不联网/不执行/不全量分析/不 Web/不强制门禁 | 只读沙箱、无网络依赖、CLI 退出码交由调用方 | `common/file_io.py`、`engine.py` |
| 4.1 性能 | 10 s/500 条、300 ms/文件、1 s/5 MB、200 MB、单次读取 | 快照缓存、分块扫描、时间预算、无第三方解析器 | `common/file_io.py`、四模块 |
| 4.2 可靠性 | 不崩溃、跳过继续、模块降级、确定性、只读 | 顶层异常捕获、`skip_reason`、`degraded_modules`、显式排序 | `engine.py`、`common/models.py` |
| 4.3 安全性 | 不执行/不联网/路径沙箱/脱敏/不写仓库 | 状态机代码视图、无网络导入、`commonpath` 校验、`mask_secret` | `common/file_io.py`、`common/config.py` |
| 4.4 可维护性 | 稳定 rule_id、阈值集中、中文文案、统计完整 | `rule_id` 强制必填、`RuleConfig`、`render_text`、`CheckSummary` | `common/models.py`、`common/config.py`、`common/report.py` |
| 4.5 兼容性 | Win/Linux 一致、UTF-8/BOM/GB18030、中文保留、`\` 与 `/` | 路径归一化、编码回退、Unicode 排序、统一 `/` 输出 | `common/manifest.py`、`common/file_io.py` |

### 2.11.2 核心能力映射

| spec 条款 | 需求要点 | 设计章节 | 实现位置 | rule_id / 数据 | 验证用例 |
|-----------|---------|---------|---------|---------------|---------|
| 5.1.1 第 1 条 | 「状态 + 空白 + 路径」解析 | 1.1.3 A、2.5 | `common/manifest.py` | `ChangeEntry` | `test_manifest.test_parse_format` |
| 5.1.1 第 2 条 | 状态仅 A/M/D，其他非法 | 1.1.3 A | `common/manifest.py` | `UnparsedLine` | `test_manifest.test_unknown_status` |
| 5.1.1 第 3 条 | 小写 a/m/d 等价 | 1.1.3 A | `common/manifest.py` | `ChangeStatus` | `test_manifest.test_lowercase_status` |
| 5.1.1 第 4 条 | 路径归一化保留中文/大小写 | 2.1.3（4） | `common/manifest.py` | `ChangeEntry.path` | `test_manifest.test_path_normalize` |
| 5.1.1 第 5 条 | 空行/`#` 行忽略 | 1.1.3 A | `common/manifest.py` | 不计入统计 | `test_manifest.test_ignore_blank_comment` |
| 5.1.1 第 6 条 | 非法行登记不中断 | 2.7.3 | `common/manifest.py`、`engine.py` | `UnparsedLine` | `test_manifest.test_missing_path` |
| 5.1.1 第 7 条 | 重复路径合并、末次状态 | 1.1.3 A、2.6.3 | `common/manifest.py` | `duplicate_count` | `test_manifest.test_duplicate_merge` |
| 5.1.1 第 8 条 | D 状态仅命名检查 | 2.5.1、2.6.2 | `engine.py`、`naming.py` | 无快照 | `test_engine.test_deleted_status_no_read` |
| 5.1.1 第 9 条 | 只读约束 | 2.1.3（6） | `common/file_io.py` | — | `test_engine.test_read_only` |
| 5.1.1 第 10 条 | 非法行不当路径读取 | 2.1.3（4） | `common/manifest.py`、`file_io.py` | — | `test_manifest.test_no_fs_access_on_invalid` |
| 5.2.1 第 1 条 | 非法字符必须修改 | 2.5.1（3） | `naming.py` | `naming-001` | `test_naming.test_illegal_chars` |
| 5.2.1 第 2 条 | >120 字符必须修改 | 2.5.1（3） | `naming.py` | `naming-002` | `test_naming.test_long_name` |
| 5.2.1 第 3 条 | 命名风格优化建议 | 2.5.1（3） | `naming.py` | `naming-003` | `test_naming.test_style_advice` |
| 5.2.1 第 4 条 | 中文名仅建议、禁止报错 | 2.5.1（3）、2.8.1 | `naming.py` | `naming-004` | `test_naming.test_chinese_name_advice_only` |
| 5.2.1 第 5 条 | 目录归属必须修改 | 2.5.1（3） | `naming.py` | `naming-005` | `test_naming.test_wrong_directory_must_fix` |
| 5.2.1 第 6 条 | 目录归属优化建议 | 2.5.1（3） | `naming.py` | `naming-006` | `test_naming.test_root_source_advice` |
| 5.2.1 第 7 条 | 扩展名与目录映射表 | 2.5.1（4） | `common/config.py` | `directory_map` | `test_naming.test_directory_map` |
| 5.2.1 第 8 条 | 问题去重与收敛 | 2.5.1（5） | `naming.py` | 合并策略 | `test_naming.test_merge_style_issues` |
| 5.2.1 第 9 条 | 建议含具体名称/目录 | 2.5.1（5） | `naming.py` | `suggestion` | `test_naming.test_suggestion_has_example` |
| 5.2.1 第 10 条 | 中文/拼音/连字符不得判必须修改 | 2.5.1（3） | `naming.py` | `naming-003/004` | `test_naming.test_no_must_fix_for_chinese` |
| 5.3.1 第 1 条 | 仅 A/M 的 `.py/.c` 扫描 | 2.5.2（1）、2.6.2 | `engine.py`、`code_scan.py` | — | `test_code_scan.test_scope` |
| 5.3.1 第 2 条 | 文件头注释（优化） | 2.5.2（3） | `code_scan.py` | `code-001` | `test_code_scan.test_module_header` |
| 5.3.1 第 3 条 | 公开函数/`main` 缺注释必须 | 2.5.2（3） | `code_scan.py` | `code-002` | `test_code_scan.test_public_function_comment` |
| 5.3.1 第 4 条 | 内部短函数缺注释仅建议 | 2.5.2（3） | `code_scan.py` | `code-003` | `test_code_scan.test_static_helper_advice` |
| 5.3.1 第 5 条 | 注释位置判定口径 | 2.5.2（2） | `code_scan.py` | — | `test_code_scan.test_comment_position` |
| 5.3.1 第 6 条 | 高危写法必须修改 | 2.5.2（3） | `code_scan.py` | `code-004/005/006` | `test_code_scan.test_high_risk` |
| 5.3.1 第 7 条 | 可疑写法优化建议 | 2.5.2（3） | `code_scan.py` | `code-007` | `test_code_scan.test_suspicious` |
| 5.3.1 第 8 条 | 每条代码问题带行号 | 2.5.2（4） | `code_scan.py` | `Finding.line_no` | `test_code_scan.test_line_number` |
| 5.3.1 第 9 条 | 注释中英文均可 | 2.5.2（2） | `code_scan.py` | — | `test_code_scan.test_chinese_comment_ok` |
| 5.3.1 第 10 条 | 不执行/不做风格必须修改/告警带行号 | 2.1.3（6）、2.5.2（4） | `code_scan.py` | — | `test_engine.test_no_code_execution` |
| 5.4.1 第 1 条 | 仅 A/M 的 `.md` 检查 | 2.5.3（1） | `engine.py`、`link_check.py` | — | `test_link_check.test_scope` |
| 5.4.1 第 2 条 | 识别行内/图片/引用/裸链接 | 2.5.3（2） | `link_check.py` | — | `test_link_check.test_extract_types` |
| 5.4.1 第 3 条 | 空目标必须修改 | 2.5.3（3） | `link_check.py` | `link-001` | `test_link_check.test_empty_target` |
| 5.4.1 第 4 条 | 括号不闭合必须修改 | 2.5.3（3） | `link_check.py` | `link-002` | `test_link_check.test_unclosed` |
| 5.4.1 第 5 条 | 引用缺定义必须修改 | 2.5.3（3） | `link_check.py` | `link-003` | `test_link_check.test_missing_definition` |
| 5.4.1 第 6 条 | 本地绝对路径优化建议 | 2.5.3（3） | `link_check.py` | `link-004` | `test_link_check.test_absolute_path` |
| 5.4.1 第 7 条 | 未编码空格必须修改 | 2.5.3（3） | `link_check.py` | `link-005` | `test_link_check.test_space_in_target` |
| 5.4.1 第 8 条 | http/localhost/空文本建议 | 2.5.3（3） | `link_check.py` | `link-006` | `test_link_check.test_protocol_advice` |
| 5.4.1 第 9 条 | 中文/锚点容忍 | 2.5.3（2、3） | `link_check.py` | `link-007` | `test_link_check.test_chinese_anchor_ok` |
| 5.4.1 第 10 条 | 行号 + 原文 ≤ 60 | 2.5.3（2） | `link_check.py` | `excerpt` | `test_link_check.test_line_and_excerpt` |
| 5.4.1 第 11 条 | 不联网/不判 404/代码块不报 | 2.5.3（1） | `link_check.py` | — | `test_link_check.test_skip_code_block` |
| 5.5.1 第 1 条 | 1～5 MB 优化建议 | 2.5.4（2） | `sensitive.py` | `sens-001` | `test_sensitive.test_warn_size` |
| 5.5.1 第 2 条 | >5 MB 必须修改 | 2.5.4（2） | `sensitive.py` | `sens-002` | `test_sensitive.test_fail_size` |
| 5.5.1 第 3 条 | 二进制仅按体积 | 2.5.4（1、3） | `sensitive.py` | `binary_extensions` | `test_sensitive.test_binary_size_only` |
| 5.5.1 第 4 条 | D 状态跳过体积 | 2.5.4（1） | `engine.py`、`sensitive.py` | — | `test_sensitive.test_deleted_skip` |
| 5.5.1 第 5 条 | 私钥/令牌必须修改 | 2.5.4（2） | `sensitive.py` | `sens-003/004` | `test_sensitive.test_private_key_token` |
| 5.5.1 第 6 条 | 明文密码/连接串必须修改 | 2.5.4（2） | `sensitive.py` | `sens-005` | `test_sensitive.test_password_conn` |
| 5.5.1 第 7 条 | 高熵/长 hex/占位优化建议 | 2.5.4（2） | `sensitive.py` | `sens-006` | `test_sensitive.test_entropy_advice` |
| 5.5.1 第 8 条 | 教学示例豁免 | 2.5.4（1、2） | `sensitive.py` | `placeholder_context_words` | `test_sensitive.test_example_exemption` |
| 5.5.1 第 9 条 | 脱敏前 4 字符 | 2.5.4（4） | `sensitive.py` | `mask_secret` | `test_sensitive.test_mask` |
| 5.5.1 第 10 条 | 不验证密钥/不写文件/二进制不文本匹配 | 2.1.3（6） | `sensitive.py` | — | `test_sensitive.test_no_network_no_write` |
| 5.6.1 第 1 条 | 单一入口 | 2.2.2（1） | `engine.py` | `run_check` | `test_engine.test_single_entry` |
| 5.6.1 第 2 条 | 按文件分组 | 2.6.3 | `engine.py` | `FileGroup` | `test_engine.test_group_by_file` |
| 5.6.1 第 3 条 | 四必填字段 + 级别取值 | 2.3.2（3） | `common/models.py` | `Finding` | `test_engine.test_finding_contract` |
| 5.6.1 第 4 条 | 统计口径 | 2.3.2（4） | `common/models.py` | `CheckSummary` | `test_engine.test_summary_counts` |
| 5.6.1 第 5 条 | 稳定排序 | 2.6.3 | `engine.py` | 排序键 | `test_engine.test_sort_order` |
| 5.6.1 第 6 条 | 摘要先必须修改并引导 | 2.6.4 | `common/report.py` | `render_text` | `test_engine.test_text_summary` |
| 5.6.1 第 7 条 | 内存对象 + JSON 中文不转义 | 2.2.2（2）、2.6.5 | `common/report.py` | `report_to_json` | `test_engine.test_json_utf8` |
| 5.6.1 第 8 条 | 退出状态语义 | 2.7.2 | `engine.py` | `ExitCode` | `test_cli.test_exit_codes` |
| 5.6.1 第 9 条 | 空结果结构完整 | 2.3.2（4）、2.6.5 | `engine.py` | 全零报告 | `test_engine.test_empty_report` |
| 5.6.1 第 10 条 | 降级可见 | 2.7.3、2.6.4 | `engine.py`、`report.py` | `degraded_modules`/`warnings` | `test_engine.test_degrade_visible` |
| 5.6.1 第 11 条 | 无英文堆栈/不合并文件/不写文件 | 2.7.4 | `engine.py`、`report.py` | — | `test_cli.test_no_stack_trace` |
| 6.1 | `ChangeEntry` 约束 | 2.3.2（2） | `common/models.py` | `ChangeEntry` | `test_manifest.test_entry_contract` |
| 6.2 | `Finding` 约束 | 2.3.2（3） | `common/models.py` | `Finding` | `test_engine.test_finding_contract` |
| 6.3 | `CheckReport` 约束 | 2.3.2（4、5） | `common/models.py` | `CheckReport` | `test_engine.test_report_contract` |
| 6.4 | `RuleConfig` 约束 | 2.8 | `common/config.py` | `RuleConfig` | `test_cli.test_config_fallback` |
| 7 第 1～5 条 | 五个规则文件 | 2.4.1 | `naming.py`、`code_scan.py`、`link_check.py`、`sensitive.py`、`engine.py` | — | `test_engine.test_delivery_files_exist` |
| 7 第 6 条 | `backend/requirements.txt` | 2.10.4 | `backend/requirements.txt` | 零依赖 | `test_engine.test_requirements_txt` |
| 7 第 7 条 | `sample_changes.txt` | 2.10.2 | `backend/tests/fixtures/sample_changes.txt` | — | `test_engine.test_sample_manifest` |
| 7 第 8 条 | 中文使用说明 | 2.10.1 | `docs/rules_engine_usage.md` | — | 文档评审 |
| 7.1 第 1 条 | 五文件同时存在 | 2.4.1 | 五个路径 | — | `test_engine.test_delivery_files_exist` |
| 7.1 第 2 条 | requirements 仅依赖/注释 | 2.10.4 | `requirements.txt` | — | `test_engine.test_requirements_txt` |
| 7.1 第 3 条 | 样例覆盖四模块 | 2.10.2 | `sample_changes.txt` | — | `test_engine.test_sample_manifest_covers_all_modules` |
| 7.1 第 4 条 | 两次执行一致 | 2.1.3（5） | `engine.py` | — | `test_engine.test_report_is_deterministic` |

## 2.12 关键设计决策与风险

### 2.12.1 设计决策记录

| 编号 | 决策 | 备选方案 | 选择理由 | 影响 |
|------|------|---------|---------|------|
| D1 | 四模块**串行**执行 | 线程池并行 | 规则引擎瓶颈在磁盘 I/O，100 个文件的量级串行即可满足 10 s；并行会引入异常顺序与结果顺序不确定性，违反 spec 4.2 第 4 条 | 流程图用 fork 表达逻辑维度，实现串行；后续如需并行，可用 `ThreadPoolExecutor` 并保持排序后置 |
| D2 | 四模块共享 `FileSnapshot` | 各模块独立读取 | spec 4.1 第 4 条要求单模块不重复读取，共享快照进一步把磁盘读取降到"每文件 1 次"，并保证四模块看到同一版本内容 | 需在 engine 中统一创建快照，D 状态不创建 |
| D3 | 零第三方依赖（标准库） | 引入 `markdown`/`pyyaml`/`pytest` | 学生环境安装成本高、Python 环境当前不可用；自研轻量 Markdown 解析足够覆盖 spec 5.4 的格式检查 | 链接解析需自行处理代码块/括号配对；用测试矩阵约束能力边界 |
| D4 | 对外数据用冻结 dataclass + 元组 | 字典/可变对象 | 类型安全、字段约束集中、可确定性序列化；避免模块间共享可变状态 | 新增字段必须带默认值；内部聚合用临时列表再冻结 |
| D5 | `rule_id` 实现层强制必填 | 沿用 spec 的"可选" | spec 4.4 第 1 条明确"每条问题必须携带稳定规则标识"，两条约束冲突时取更严格者 | 所有规则表已分配稳定编号；后续只增不改 |
| D6 | 模块降级退出码为 3（而非 1） | 降级返回 1 | 让 CI 区分"检查完成但有违规"与"检查未完整执行"（spec 5.6.1 第 8 条 b） | 优先级 `2 > 3 > 1 > 0` |
| D7 | naming 只依赖路径，不读内容 | 读取文件确认类型 | spec 5.1.1 第 8 条要求 D 状态零读取；以扩展名 + 路径前缀判定足够覆盖 5.2.1 | 无扩展名/未知扩展名按 spec 5.2.3 跳过目录判定 |
| D8 | 大文件样例不在仓库提交 | 提交 6 MB 二进制 | 避免共享学习仓库体积膨胀（与 spec 5.5 的教育目标一致）；由测试在临时目录生成 | 直接运行样例时该条目显示"文件不存在"跳过，文档已说明 |
| D9 | `directory_map` 配置整体替换 | 深合并 | 避免部分覆盖导致规则碎片化、难以排查；要求配置必须含 `.md/.c/.h/.py` 四项，否则回退默认 | 调用方自定义目录体系时一次给全 |
| D10 | 文本扫描用"代码视图/行级正则"，不做完整语法分析 | 引入编译器前端 | spec 1.4 明确不做全量静态分析；轻量方案满足注释/高危/链接需求，且能控制 300 ms 预算 | C 宏包裹/语法异常时跳过而非误报 |
| D11 | CLI 固定"有必须修改即退出 1" | 提供 `--fail-on` 开关 | spec 5.6.1 第 8 条为硬性要求；spec 1.4 第 7 条说明"是否作为 CI 门禁由调用方决定"，调用方可通过忽略退出码实现 | 不提供关闭开关，减少配置面 |
| D12 | 显式 `--output` 才写文件 | 默认写报告文件 | spec 4.3 第 5 条、5.6.1 第 11 条禁止默认写入仓库 | 默认只写 stdout |

### 2.12.2 风险与缓解

| 编号 | 风险 | 影响 | 缓解措施 | 残余风险 |
|------|------|------|---------|---------|
| R1 | 当前 Python 解释器不可用（`D:\python\python.exe` 启动失败） | 无法运行实现与测试 | 实现阶段第一步修复/切换解释器；设计仅依赖标准库，修复后无需安装 | 中：环境问题可能阻塞交付验证 |
| R2 | C 函数识别基于正则，宏包裹/复杂声明可能漏识别 | 漏报注释问题 | 无法可靠识别时跳过该片段，绝不误报（spec 5.3.3 第 3 条）；测试覆盖常见定义形态 | 低：漏报优于误报，符合引导式定位 |
| R3 | 自研 Markdown 链接解析不覆盖全部 CommonMark 语法 | 少数合法链接误判或漏检 | 明确只检查 spec 5.4 列出的五类结构；代码块/行内代码剔除；跨行仅在结构不成立时报错；测试覆盖典型写法 | 低：不做可达性验证，格式判定边界清晰 |
| R4 | 大文件规则缺少可提交的样例 | 样例清单直接运行时无法触发 `sens-002` | 单元/集成测试临时生成大文件；文档说明本地生成方式；敏感信息模块仍由 `sens-004/005` 覆盖输出 | 低：验收第 3 条通过其他敏感规则满足四模块覆盖 |
| R5 | 300 ms/文件与 5 MB 文本 1 s 预算口径冲突 | 性能验收争议 | 明确：300 ms 针对普通文件全流程；> 5 MB 文本按 spec 4.1 第 2 条单独给 1 s，且已由 `sens-002` 判必须修改；测试分别度量 | 低：文档已固化口径 |
| R6 | Windows 路径大小写/符号链接差异 | 沙箱误判或绕过 | 归一化 + `realpath` + `casefold` 比较；测试覆盖 `\`、盘符、UNC、符号链接 | 低：Linux 下行为一致 |
| R7 | `.svg` 被归为二进制，可能漏检脚本/文本中的令牌 | 漏报 | 文档说明可在配置中移除 `.svg`；默认遵循 spec 5.5.1 第 3 条"图片只按体积判定" | 低：可通过配置调整 |
| R8 | 中文路径/文件名在某些终端显示异常 | 学生阅读困难 | 输出统一 UTF-8、`ensure_ascii=False`；不转义中文；测试覆盖中文路径 | 低：终端需支持 UTF-8 |
| R9 | 模块异常信息可能包含英文异常文本 | 违反"中文为主提示" | 对外只输出预制中文原因；原始异常仅 `--debug` 到 stderr | 低 |
| R10 | 报告问题过多导致终端难以阅读 | 学生放弃阅读 | 每文件每规则聚合上限 5 条；必须修改优先；摘要只给统计与分组 | 低 |

### 2.12.3 设计完成标准

本设计完成的判定条件：

1. spec 5.1～5.6 的每条业务规则均能在 2.5、2.6、2.7 找到唯一落点，并在 2.11 建立映射。
2. 四个检查模块与汇总入口的接口签名、数据结构、异常与退出码均已固定，实现阶段无需再决策。
3. 交付物路径、样例清单内容、requirements.txt 策略、测试用例矩阵均已明确到文件级。
4. 与 spec 的冲突点（`rule_id` 可选 vs 必须、并行 vs 串行、样例大文件）均已显式决策并记录理由。
5. 本文档不含逐行实现代码；实现阶段按 2.4 的文件划分与 2.5 的判定表直接编码。
6. 2.4.3 已逐文件固定仓库相对路径与全部公开函数签名，2.4.4 已固定文件级导入方向，2.4.5 已统一与 2.2 的口径；实现阶段不得新增未列出的公共函数或越界路径。

---

**文档结束**
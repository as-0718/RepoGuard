# RepoGuard 全仓巡检与 README 目录生成使用说明

## 1. 能力概览

阶段 3 新增两项只读离线能力：

- 全仓健康巡检：递归扫描仓库，复用命名、代码、链接、敏感信息四类既有检查，输出结构化报告。
- README 目录生成：扫描 Markdown 与 Demo 工程，生成目录索引、现有 README 差异与可直接替换的目录片段。

两项能力都不会修改被巡检仓库，不联网，不监听端口，不启动 Web 服务，不引入第三方依赖。

## 2. 运行前准备

在 `backend/` 目录执行：

```bash
cd backend
python -m app.health.cli --help
python -m app.readme.cli --help
```

默认仓库为项目下 `demo-repo/`。也可以显式传入任意仓库根目录。

## 3. 全仓健康巡检

### 3.1 命令示例

```bash
python -m app.health.cli --repo ../demo-repo --format text
python -m app.health.cli --repo ../demo-repo --format json
python -m app.health.cli --repo ../demo-repo --format json --output ../health_report.json
python -m app.health.cli --repo ../demo-repo --zombie-days 90 --git off --max-files 2000
```

### 3.2 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--repo` | 自动查找 `demo-repo` | 仓库根目录，必须存在且为目录 |
| `--format` | `text` | `text` 或 `json` |
| `--output` | 无 | 额外写 JSON 报告，目标必须在被巡检仓库之外 |
| `--zombie-days` | `365` | 僵尸判定阈值，30～3650 天，越界回退默认并警告 |
| `--git` | `auto` | `auto`、`on`、`off`；`off` 完全不调用 git |
| `--max-files` | `5000` | 文件数上限，30～50000 |
| `--config` | 无 | JSON 规则配置，透传给既有规则引擎 |
| `--debug` | 关闭 | 仅此模式向 stderr 输出调试堆栈 |

### 3.3 报告内容

报告包含：

- 文件总数、Markdown 数、代码文件数、Demo 已确认/疑似数量
- 问题总数、高风险数、建议数
- 按文件分组的问题位置、风险等级、修改建议、规则来源
- 僵尸候选、无法判定项、降级项、警告
- 扫描时间与耗时

风险等级只映射既有规则级别：`必须修改 → 高风险`，`优化建议 → 建议`，不新增分级。

### 3.4 僵尸与废弃文件口径

只有在以下三类依据同时成立时才输出僵尸候选：

1. Git 最近提交时间或可信的 mtime 超过阈值；
2. 全仓引用扫描结果为 0；
3. 文件不属于入口、构建、示例、配置文件等豁免范围。

依据不足时输出「无法判定」并写明原因，不会硬猜。可能的无法判定原因：

- Git 历史不可用且 mtime 疑似批量检出
- 引用统计不完整，存在无法读取的文本文件
- 只有部分文件有可信时间依据
- 入口、构建、示例或配置文件不适用僵尸判定

mtime 判定会检查是否超过 80% 文件集中在 1 小时窗口；若集中，则视为批量检出，不作为时间依据。

### 3.5 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 无高风险、无降级 |
| `1` | 存在高风险问题 |
| `2` | 输入错误（根非法、自扫描拒绝、参数错误、输出路径非法） |
| `3` | 部分降级、执行异常或存在降级项 |

优先级为 `2 > 3 > 1 > 0`。僵尸候选与无法判定本身不触发退出码 1。

## 4. README 目录生成

### 4.1 命令示例

```bash
python -m app.readme.cli --repo ../demo-repo --format text
python -m app.readme.cli --repo ../demo-repo --format json
python -m app.readme.cli --repo ../demo-repo --readme README.md --format text
python -m app.readme.cli --repo ../demo-repo --format json --output ../readme_report.json
```

### 4.2 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--repo` | 自动查找 `demo-repo` | 仓库根目录 |
| `--format` | `text` | `text` 或 `json` |
| `--readme` | 自动查找 README.md/readme.md | 必须位于仓库根内 |
| `--output` | 无 | 额外写 JSON 报告，必须在仓库根之外且不得覆盖 README |
| `--max-files` | `5000` | 文件数上限 |
| `--debug` | 关闭 | 仅此模式向 stderr 输出堆栈 |

### 4.3 目录索引规则

- Markdown 标题优先取首个一级标题；没有一级标题时回退文件名。
- 会自动跳过 YAML 头、HTML 注释与围栏代码块中的伪标题。
- 文档索引按相对路径生成，空格路径使用尖括号包裹，中文路径不 percent-encode。
- Demo 工程采用保守识别：有入口文件或构建文件才确认；只有源码特征时标为「疑似 Demo」；依据不足标为无法判定。
- 分区固定为「文档索引」「Demo 工程」，空分区显示「（无）」。

### 4.4 与现有 README 对比

支持识别三种目录区块：

1. `<!-- TOC -->` 与 `<!-- /TOC -->`
2. `<!-- BEGIN TOC -->` 与 `<!-- END TOC -->`
3. 标题「目录」「文档目录」「Table of Contents」「Contents」

未识别目录区块时，不猜测插入位置，输出完整替换片段并提示人工选择插入位置。

差异类型包括新增、删除、移动、标题变化。报告只输出文本与替换片段，**不会修改 README**；需要落盘时请人工确认后替换。

### 4.5 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 无差异或对比完成且无差异 |
| `1` | 存在目录差异 |
| `2` | 输入错误（根非法、README 越界、输出路径非法） |
| `3` | 部分降级、目录区块缺失、无法判定或执行异常 |

## 5. 只读与安全说明

- 巡检与 README 扫描只读取文件，不写入被巡检仓库。
- `--output` 只允许写被巡检仓库之外的报告文件，不得覆盖 README。
- 不联网，不请求外链，不探测 404。
- 不执行被检查代码，不使用 `eval`、`exec` 或 Web 服务。
- 不导入 FastAPI、uvicorn、starlette、pydantic。
- 跳过 `.git`、`__pycache__`、虚拟环境、构建产物、依赖目录与符号链接。
- 仓库根包含 RepoGuard 工具自身 `backend/app/` 时拒绝巡检。

## 6. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 3 且提示 Git 不可用 | 仓库不是 Git 工作区 | 可接受降级，或使用 `--git off` 明确关闭 Git 依据 |
| 大量「无法判定」 | 文件时间集中在 1 小时窗口或引用扫描不完整 | 检查是否刚批量检出；补充可读文本引用 |
| 文件数超过上限 | 仓库文件很多 | 使用 `--max-files` 调整，或缩小巡检范围 |
| README 未找到/区块未识别 | 根目录没有 README 或没有目录标记 | 使用输出片段人工插入，本工具不写 README |
| 页面/API 行为 | 本阶段未修改阶段 1 CLI 与阶段 2 Web API | 原有命令与 FastAPI 路由保持不变 |

## 7. 兼容性

- 阶段 1 CLI：`python -m app.core.rules.engine` 参数、退出码、text/JSON 输出不变。
- 阶段 2 Web API：`backend/app/api/**` 与 `backend/app/static/index.html` 零改动。
- 依赖：`backend/requirements.txt` 未新增任何依赖，本阶段全部使用 Python 3.10+ 标准库。
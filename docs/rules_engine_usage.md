# RepoGuard 规则引擎使用说明

## 1. 规则引擎能做什么

规则引擎面向高校课程与科创社团共享学习仓库，对一次变更清单执行四类只读检查：

- 命名与目录检查：文件名是否规范、文件是否放错目录。
- 代码检查：Python / C 文件是否缺少注释；是否出现高危写法；是否遗留调试断点、`TODO/FIXME/HACK/XXX` 标记；以及常见 bug 模式（可变对象默认参数、用 `== None` / `!= None` 比较身份、空函数体等）。
- 链接检查：Markdown 链接格式是否完整、是否使用本机绝对路径。
- 敏感信息与大文件检查：是否提交密钥、令牌或过大的文件。

问题分为两级：「必须修改」影响仓库可用性或安全，「优化建议」用于帮助新人养成更好的提交习惯。中文文件名只会给出优化建议，不会阻止提交。

规则引擎本身只读、离线、不执行 Git、不编译或运行被扫描代码；桌面版对极少数白名单规则的选择性修复由独立的 fixer 层承担，详见 [fixer 使用说明](fixer_usage.md)。

## 2. 如何生成变更清单

变更清单每行格式为「状态 + 空格 + 文件路径」：

```text
A docs/lab03_串口通信实验.md
M lab/uart/uart_demo.c
D notes/old_lab02.md
```

- `A` 表示新增，`M` 表示修改，`D` 表示删除。
- 状态大小写等价，`a`、`m`、`d` 同样可用。
- 空行与以 `#` 开头的注释行会被忽略。
- 路径分隔符 `\` 与 `/` 均可，引擎内部统一为 `/`。
- 路径必须位于仓库根目录内，不能使用 `../` 跳出仓库。

手工整理示例：

```text
# 本次 PR 的变更
A docs/lab04_传感器实验.md
M lab/uart/uart_demo.c
```

使用 Git 生成时，可先执行 `git diff --name-status`，再把输出另存为 UTF-8 文本；引擎本身不调用 Git。

## 3. 如何调用汇总入口

工作目录固定为 `backend/`。

进程内调用：

```python
from pathlib import Path
from app.core.rules import run_check, render_text

report = run_check(
    manifest_text="A docs/lab03_串口通信实验.md\nM lab/uart/uart_demo.c\n",
    repo_root=Path("../demo-repo"),
)
print(render_text(report))
```

命令行调用：

```text
cd backend
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo
```

参数表：

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--manifest` | 是 | — | 清单文件路径；`-` 表示从标准输入读取 |
| `--repo` | 否 | `.` | 仓库根目录 |
| `--format` | 否 | `text` | 输出格式，可选 `text` 或 `json` |
| `--output` | 否 | 无 | 额外写入 JSON 报告的文件路径 |
| `--config` | 否 | 无 | JSON 配置文件路径 |
| `--debug` | 否 | 关闭 | 出现异常时向标准错误输出调试信息 |

## 4. 如何阅读报告

报告按文件分组，每个文件只出现一次。文件内先列「必须修改」，再列「优化建议」。

每条问题包含：

- 行号（文件级问题可能没有行号）。
- 问题描述：说明发生了什么。
- 修改建议：给出可以直接照做的改法。

报告末尾还会出现：

- 未完成检查的文件：例如文件不存在、编码无法识别或路径超出仓库范围。
- 模块降级说明：某个检查模块执行异常时，会说明结果可能不完整。
- 提示：配置回退、空清单等补充信息。

## 5. 退出码说明

| 退出码 | 含义 |
|--------|------|
| `0` | 没有必须修改项，可能只有优化建议或没有问题 |
| `1` | 至少存在 1 条必须修改 |
| `2` | 输入错误，例如仓库根不存在或清单不可读 |
| `3` | 执行异常，例如模块降级或报告写入失败 |

优先级为 `2 > 3 > 1 > 0`。流水线应区分「检查完成但有违规」与「检查没有完整执行」。

## 6. 配置说明

可通过 `--config` 提供 UTF-8 JSON 对象，常用可配置项包括：

- `large_file_warn_mb`：大文件优化建议阈值，默认 `1.0`。
- `large_file_fail_mb`：大文件必须修改阈值，默认 `5.0`。
- `code_scan_max_mb`：超过该体积跳过代码内容检查，默认 `5.0`。
- `per_file_budget_ms`：单文件检查预算，默认 `300`。
- `link_max_per_file`：单文件链接数量阈值，默认 `200`。
- `directory_map`：扩展名到推荐目录的映射。

固定不可配置项：

- 中文文件名只能给优化建议，不能升级为必须修改。
- PEM 私钥与已知真实令牌必须判定为必须修改。
- 引擎只读、离线，不执行被扫描代码。
- 输出语言固定为简体中文。
- 敏感值固定脱敏为「前 4 个字符 + `****`」。

## 7. 样例运行

仓库提供了样例清单与样例仓库，可直接运行：

```text
cd backend
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo
python -m app.core.rules.engine --manifest tests/fixtures/sample_changes.txt --repo ../demo-repo --format json
```

`demo-repo/assets/large_sample.mp4` 默认不提交。需要在本地验证大文件规则时，可自行生成大于 5 MB 的占位文件，测试完成后删除，不要提交到仓库。

## 8. 常见问题

- 文件编码无法识别：请把文件另存为 UTF-8 后重试；引擎会回退尝试 GB18030。
- 路径超出仓库范围：清单中的路径必须位于 `--repo` 指向的目录内，不能使用 `../`。
- 模块降级：某个检查模块出现异常时，其余模块仍会继续，报告末尾会提示「结果可能不完整」。
- 中文终端显示异常：请确认终端使用 UTF-8 编码；JSON 输出不会转义中文。
- 链接检查不判断链接是否真实可达：引擎只检查格式，不联网、不请求 404。
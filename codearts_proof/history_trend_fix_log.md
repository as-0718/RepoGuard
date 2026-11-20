# 分批修复样例仓库与历史趋势折线记录

## 一、背景与目标

demo-repo 是 RepoGuard 自带的教学样例仓库，里面同时放了正反两类样例。本轮目标是：
按规则类别分 6 批逐步改掉其中的问题文件，每批改完做一次真实巡检并落一条历史快照，
让历史记录页的趋势折线呈现出问题数量逐轮下降的走势；最后把这份历史库随便携包一起带走，
打开 exe 就能看到这条递减折线。

基线首轮巡检共 **62** 条问题（高风险 27、建议 35），收尾时剩 **16** 条（高风险 10、建议 6）。

## 二、落库机制与本轮后端调整

- 历史快照存在本地 SQLite 的 `snapshots` 表，只有真实扫描（非缓存命中）才会写库；
  缓存命中不落库。两次强制刷新间隔小于 10 秒会被节流，不会重复落快照。
- **本轮调整**：历史落库和查询用的仓库标识（repo_key）原先取仓库绝对路径的哈希。
  开发态源码路径和打包后 `resources/demo-repo` 路径不一样，哈希对不上，开发态攒下的快照
  拷进包里按路径哈希就查不到，换目录、换机器也会丢。
  现已把落库与查询的 repo_key 改为**仓库目录名**（`descriptor.label` / `root.name`，即 `demo-repo`），
  缓存键仍保留路径哈希不变。改动落在 `backend/app/dashboard/router.py`，全量回归 480 条测试通过（skipped=4）。

## 三、七次巡检快照趋势

| 快照 | 本地时间 | 问题总数 | 高风险 | 建议 | 说明 |
|---|---|---|---|---|---|
| #1 | 01:12:56 | 62 | 27 | 35 | 基线，未整改 |
| #2 | 01:16:20 | 55 | 23 | 32 | 批次 1 敏感信息 |
| #3 | 01:17:57 | 48 | 19 | 29 | 批次 2 命令注入 / 动态执行 |
| #4 | 01:18:58 | 42 | 15 | 27 | 批次 3 C 缓冲区 / 魔法数 |
| #5 | 01:20:43 | 29 | 13 | 16 | 批次 4 Python 代码质量 |
| #6 | 01:22:46 | 24 | 13 | 11 | 批次 5 命名 / 文档链接 |
| #7 | 01:26:16 | 16 | 10 | 6 | 批次 6 收尾整改 |

三条曲线（问题总数、高风险、建议）在历史页均为单调递减，截图见
`stage6_history_trend/01_历史趋势折线.png`。

## 四、分批整改明细

### 批次 1：敏感信息（62 → 55，消 7 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text3/backend/app/aws_key.py` | sens-004 高风险（AKIA 访问密钥） | 改 `os.getenv` 读取，默认值用 `<your-access-key>` 占位 |
| `text3/backend/app/third_party_tokens.py` | sens-004 高风险（5 处令牌前缀聚合为 1 条） | 五类令牌全部改 `os.getenv`，占位符兜底 |
| `text3/backend/app/db_connection.py` | sens-005 高风险（带口令连接串） | 连接串改 `os.getenv("DB_DSN", "")`，不再写明文账号口令 |
| `text3/backend/app/hex_secret.py` | sens-006 建议（长十六进制串） | 种子值改 `os.getenv`，去掉长随机串 |
| `text1/backend/app/key_sample.pem` | sens-003 高风险（PEM 私钥头）+ sens-006 建议 | 私钥内容换成占位说明文本，去掉 BEGIN/END 私钥头 |
| `text3/assets/large_note.txt` | sens-001 建议（1.18 MB 大文件） | 纯占位填充文本，直接删除 |

### 批次 2：命令注入与动态执行（55 → 48，消 7 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text1/backend/app/unsafe_input.py` | code-006 高、code-005 高（eval）、code-007 建议（os.system、裸 except） | 去掉命令拼接、eval、os.system 和裸 except，改为正则白名单校验的纯函数 |
| `text2/backend/app/exec_call.py` | code-005 高（exec） | 去掉 exec，动作名走白名单字典映射 |
| `text2/backend/app/shell_subprocess.py` | code-006 高（shell=True）、code-007 建议（subprocess） | 只构造参数列表并校验主机名，不再实际拉起外部进程、不用 shell |

### 批次 3：C 缓冲区风险与魔法数（48 → 42，消 6 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text2/lab/buffer_risk.c` | code-002 高（main 缺注释）、code-004 高 ×3（gets / strcat / sprintf）、code-001 建议（文件头缺注释） | 补文件头与函数注释；gets 换 fgets、strcat 换 strncat、sprintf 换 snprintf，显式带缓冲区长度 |
| `text2/lab/numeric_const.c` | code-007 建议（函数内长数字 5000） | 长数字提为 `#define SAMPLE_PERIOD_MS` 宏常量 |

### 批次 4：Python 代码质量（42 → 29，消 13 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text1/backend/app/debug_left.py` | code-009 建议（TODO）、code-010 建议（breakpoint） | 删遗留标记与断点，保留正常返回 |
| `text1/backend/app/empty_stub.py` | code-013 建议（函数体仅 pass） | 补实际实现，返回默认占位标识 |
| `text1/backend/app/mutable_default.py` | code-011 建议（可变默认参数） | 默认值改 `None`，函数体内按需新建列表 |
| `text1/backend/app/none_compare.py` | code-012 建议（`== None`） | 改用 `is None` 身份比较 |
| `text2/backend/app/internal_helper.py` | code-003 建议（内部短函数缺说明） | 给 `_format_line` 补文档字符串 |
| `text2/backend/app/magic_numbers.py` | code-002 高（缺 docstring）、code-007 建议（魔法数） | 补函数 docstring，重复字面量与长数字提为模块常量 |
| `text2/backend/app/no_module_docstring.py` | code-002 高（缺 docstring）、code-001 建议（模块缺说明） | 补模块说明与函数 docstring |
| `text2/backend/app/pdb_debug.py` | code-009 建议 ×2（FIXME / XXX）、code-010 建议（pdb） | 删 pdb 导入、断点与遗留标记 |

### 批次 5：命名规范与文档链接（29 → 24，消 5 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text1/assets/README.md` → `readme.md` | naming-003 建议（文件名大写） | 改为全小写下划线命名 |
| `text2/lab/Parse-Frame.c` → `parse_frame.c` | naming-003 建议（大写 + 连字符） | 改为全小写下划线命名 |
| `text3/docs/link_empty_text.md` | link-006 建议（链接文字为空） | 补上链接文字「使用指南」 |
| `text3/docs/link_parent.md` | link-007 建议（`../` 指向仓库外） | 改为仓库内相对路径 `./notes.md` |
| `text3/docs/link_private.md` | link-006 建议（内网 http 地址） | 改为 https 公开示例地址 |

### 批次 6：收尾整改（24 → 16，消 8 条）

| 文件 | 原命中规则 | 整改写法 |
|---|---|---|
| `text1/lab/uart/uart_demo.c` | code-001 建议、code-002 高、code-004 高（strcpy）、code-007 建议（while(1)） | 补文件头/函数注释；strcpy 换 strncpy 并补结束符；去掉死循环 |
| `text1/lab/uart/UART Demo-v2.C` → `uart_demo_v2.c` | naming-003 建议、code-001 建议、code-002 高 | 改名全小写下划线，补文件头与 main 注释 |
| `text1/docs/lab03_串口通信实验.md` → `lab03_serial_communication.md` | naming-004 建议（中文文件名） | 文件名改为英文下划线 |

## 五、保留的反面样例及原因

收尾后仍留 16 条问题，集中在下面几类文件，刻意没有改干净：

- `text1/backend/app/example_config.py`：sens-005、sens-004、code-001、code-002（4 条）
- `text1/docs/lab02_broken_link.md`：link-001/002/003/004/005/006/007 + naming-006（8 条）
- `text1/backend/tests/test_demo.py`、`text2/backend/app/test_misplaced.py`、`text2/backend/tests/test_clean_sample.py`：naming-005 高风险 ×3
- `text1/docs/lab03_serial_communication.md`：naming-006 建议（1 条）

保留原因：

1. **撑住规则覆盖测试**：`backend/tests/test_engine.py` 的样例清单测试要求样例仓库能命中
   `naming / code / link / sens` 四类前缀。每类至少留一个最小反例，四类覆盖断言才不会挂；
   改完后全量回归 480 条测试仍全部通过。
2. **目录前缀结构限制**：naming-005 / naming-006 规则只认路径首段是 `backend/tests`、`docs`，
   而样例文件都在 `text1 / text2 / text3` 三层前缀下，单纯在内部挪目录消不掉这两条，如实保留。
3. **教学需要**：演示时仍要能看到各类问题长什么样，保留反面样例便于对照规则说明。

## 六、打包随包携带与复验

- 后端用 PyInstaller 重打 `repoguard-backend.exe`，包含本轮 repo_key 改仓库名的改动。
- electron-builder 重打 Windows 便携包（`desktop/release/win-unpacked/`），包内带入整改后的
  `demo-repo`、前端 `web/`、后端 `backend/`。
- 打包配置的 data 目录过滤器排除了 `*.db`，因此把开发态攒下的历史库手动拷到包内
  `resources/data/repoguard.db`；repo_key 为 `demo-repo`，与包内仓库目录名一致，历史页可直接查到。
- **接口复验**：包内后端健康检查 ok；历史接口返回 7 条递减快照；总览扫描包内样例仓库为
  16 条（高风险 10、建议 6），与开发态最终态一致。
- **界面复验**：浏览器进入历史记录页，三条趋势线正常渲染并呈递减走势，截图已归档到
  `stage6_history_trend/01_历史趋势折线.png`。

## 七、遗留限制

- 同一天多次巡检，折线 x 轴的时间标签会重复；环比箭头需要两次结果不同才显示。
- 包内首次打开、触发总览加载时会再落一条当前态快照（尾部与最后一条持平）；交付预置的历史库
  已整理为 7 条干净递减记录。
- 本轮样例文件改动、后端 router.py 改动均留在工作区，未提交 git，按统一指令再提交。

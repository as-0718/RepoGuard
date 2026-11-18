# 代码生成、重构与排错过程记录

## 一、代码生成

按五阶段逐步生成功能模块，每个模块配套单元测试：

- **规则引擎**：命名/目录、代码扫描、链接检查、敏感信息与大文件检查，及公共清单/模型/报告模块；
- **Web API**：路由、接口模型、安全与白名单、设置加载、单页静态托管；
- **全仓巡检 / README 目录**：巡检服务、僵尸候选识别、README 扫描/索引/对比与 CLI；
- **Webhook / OpenAPI**：路由、签名校验、幂等、队列、解析与离线 e2e；
- **看板与部署**：后端看板服务/缓存/模型、前端 Vue 3 + ECharts 视图、部署与定时产物脚本。

测试清单见 `.codeartsdoer/evidence/stage5/test_inventory.txt`：25 个测试文件、377 个测试方法（阶段 5 口径）。

## 二、重构记录

- **看板接口接入**：阶段 5 将只读看板路由挂入既有 API 应用。接入前的 `app.py` 备份为 `.codeartsdoer/evidence/stage5/app.py.orig`，用于对比看板接口接入前后的差异。
- **冻结文件核对**：规则引擎等核心文件的 SHA-256 冻结清单见 `.codeartsdoer/evidence/stage4/baseline_hashes.txt` 与 `stage5/hashes.txt`；重构前后核对，未越界改动冻结文件。

## 三、排错记录

### 1. 既有符号链接测试失败

- **现象**：`test_repo_walk` 中 2 条测试在基线即失败，与符号链接环境有关。
- **处置**：确认为基线既有问题，不在本项目范围内改动；基线如实记录 `failures=2`，后续各阶段回归确认未新增同类失败。

### 2. Web 白名单路径安全约束

- **现象/风险**：Web 接口若接受请求参数指定任意仓库路径，可能越界读取本机目录。
- **处置**：Web 层只读取 `REPOGUARD_ALLOWED_REPOS` 环境配置内的目录，请求参数不能覆盖该配置；路径越界抛出 `RepoPathError`。

### 3. 测试复核与冻结文件哈希核对

- **做法**：每个阶段以基线测试回归 + 冻结文件哈希核对作为验收，防止重构改动越界。阶段 5 另用一次性静态校验脚本核对部署产物（T26）与定时产物（T30），脚本见 `.codeartsdoer/evidence/stage5/`。

### 4. Windows 下 Python 解释器静默无输出

- **现象**：在 cmd / PowerShell 中运行 `python -m ...` 全部静默、无任何输出、无报错。
- **排查**：系统 `python` 解析到 WindowsApps 下 0 字节商店占位别名，原有独立 Python 安装目录已失效；可用解释器为 uv 安装的 CPython 3.11.15。
- **处置**：改用可用解释器绝对路径运行，命令与输出恢复正常。

### 5. 部署产物静态校验与 SKIP 项

- **现象**：开发本机无 Docker、nginx、云 CLI、crontab，无法真实构建或上线。
- **处置**：部署与定时产物只做语法解析、配置静态校验与 dry-run；未执行的项以 SKIP 单列，不记作已上线、不记作已验证容器/nginx/云环境。

## 四、佐证文件索引

| 文件 | 含义 |
|---|---|
| `.codeartsdoer/evidence/stage4/baseline_tests.txt` | 阶段 4 基线测试输出（310 条） |
| `.codeartsdoer/evidence/stage5/baseline_tests.txt` | 阶段 5 基线测试输出（377 条） |
| `.codeartsdoer/evidence/stage5/test_inventory.txt` | 测试文件与方法清单 |
| `.codeartsdoer/evidence/stage5/hashes.txt` | 冻结文件 SHA-256 清单 |
| `.codeartsdoer/evidence/stage5/app.py.orig` | 看板接口接入前的 `app.py` 备份 |
| `.codeartsdoer/evidence/stage5/_verify_t26.py` | 部署产物静态校验一次性脚本 |
| `.codeartsdoer/evidence/stage5/_verify_t30.py` | 定时产物静态校验一次性脚本 |
| `.codeartsdoer/evidence/stage5/env.txt` | 开发环境清单（含本机路径，打包对外时只引用其结论，不外发原始文件） |

## 五、测试基线演进

| 节点 | 测试数 | 结果 |
|---|---|---|
| 阶段 4 完成后 | 310 | 2 条既有符号链接失败、1 条跳过 |
| 阶段 5 完成后 | 377 | 2 条既有符号链接失败、2 条跳过 |
| 最终回归 | 438 | 全部通过，4 条跳过 |

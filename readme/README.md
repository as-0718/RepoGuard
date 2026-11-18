# RepoGuard 作品说明文档

## 项目简介

RepoGuard 是面向课程学习与科创社团共享仓库的**只读离线自检工具**：对一次变更清单或整个仓库执行命名、代码、链接、敏感信息等检查，输出分级报告，并提供 Web API 与可视化看板。工具不联网、不执行被扫描代码、不自动修复。

## 本目录文档索引

| 文件 | 对应要求 | 内容 |
|---|---|---|
| `environment.md` | 环境依赖说明 | 运行时版本、后端/前端第三方依赖、测试基线 |
| `install.ps1` / `install.sh` | 一键安装脚本 | Windows / Linux 一键安装后端与前端依赖（不自动跑测试） |
| `deployment.md` | 部署运行步骤 | 本地运行、命令行工具、生产上线摘要、安全边界与事实声明 |
| `third_party_notice.md` | 开源组件说明 | 第三方组件版本、用途、许可证与来源 |
| `codearts_summary.md` | 码道应用总结 | 五阶段协作模式、AI 作用、测试演进与证据索引 |

## 快速开始

```bash
# 安装依赖（Windows）
powershell -ExecutionPolicy Bypass -File readme/install.ps1
# 安装依赖（Linux / macOS）
bash readme/install.sh

# 命令行巡检
cd backend
python -m app.health.cli --repo ../demo-repo --format text

# 启动 Web API（8000）与前端看板（5173），详见 deployment.md
```

## 团队信息

- 队伍名称：云珩智联
- 成员：安栩锐、邹雅雯、黄泓博
- 版本号：v1.0.0
- 联系邮箱：2397723477@qq.com
- 代码仓库：https://github.com/as-0718/RepoGuard

## 提交包结构对照

| 目录 | 内容 |
|---|---|
| `ppt/` | 作品整体介绍 PPT / PDF（场景背景、功能架构、核心亮点、码道应用说明） |
| `project/` | 可演示完整功能的作品 Demo |
| `video/` | 功能演示视频（3 分钟以内，或在线视频链接） |
| `codearts_proof/` | 码道使用证明：AI 交互记录、生成/重构/排错记录、阶段截图 |
| `readme/` | 本目录：环境依赖、安装脚本、部署步骤、开源组件说明、码道总结 |

"""第三方标识配置（已整改：各类令牌均从环境变量读取，仓库内只保留占位说明）。"""

import os

GITHUB = os.getenv("GITHUB_TOKEN", "<your-github-token>")
GITLAB = os.getenv("GITLAB_TOKEN", "<your-gitlab-token>")
SLACK = os.getenv("SLACK_TOKEN", "<your-slack-token>")
LLM = os.getenv("LLM_API_KEY", "<your-llm-key>")
GOOGLE = os.getenv("GOOGLE_API_KEY", "<your-google-key>")

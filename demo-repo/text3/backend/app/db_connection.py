"""数据库连接配置（已整改：连接串从环境变量读取，不在仓库内写明文口令）。"""

import os

DSN = os.getenv("DB_DSN", "")

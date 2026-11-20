"""随机串配置（已整改：种子值从环境变量读取，不在仓库内写长随机串）。"""

import os

SEED = os.getenv("APP_SEED", "<your-seed>")

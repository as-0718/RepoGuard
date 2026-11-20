"""云服务访问密钥配置（已整改：密钥从环境变量读取，不在仓库内写明文）。"""

import os

CLOUD_ID = os.getenv("CLOUD_ACCESS_KEY", "<your-access-key>")

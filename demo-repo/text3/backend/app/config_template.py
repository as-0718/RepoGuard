"""配置模板正面样例：凭据从环境变量读取，不写明文。"""
import os


def db_url() -> str | None:
    """从环境变量读取数据库地址，未配置时返回 None。"""
    return os.getenv("DB_URL")

"""外部输入处理示例（已整改：不再执行外部命令或动态求值，输入先做白名单校验）。"""

import re

_ALLOWED_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def run_command(name: str) -> str:
    """校验输入名称并返回规范化结果，不拼接系统命令、不做动态求值。"""
    if not _ALLOWED_NAME.match(name):
        return ""
    return name.strip()

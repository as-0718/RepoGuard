"""外部命令调用示例（已整改：命令拆成参数列表并校验主机，不再使用 shell=True）。"""

import re

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,64}$")


def build_ping_command(host: str) -> list[str]:
    """构造 ping 命令的参数列表，先校验主机名，避免拼接命令与 shell 执行。"""
    if not _HOST_RE.match(host):
        raise ValueError("主机名包含非法字符")
    return ["ping", "-c", "1", host]

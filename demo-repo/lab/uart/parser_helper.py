"""串口报文解析辅助示例：演示规范的注释与实现写法（正面样例）。"""


def split_frame(line: str) -> list[str]:
    """按换行切分报文，去掉空行后返回各帧文本。"""
    if not line:
        return []
    return [part.strip() for part in line.splitlines() if part.strip()]

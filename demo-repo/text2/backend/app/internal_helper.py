"""内部辅助函数注释示例（已整改：内部短函数补充文档字符串说明用途）。"""


def _format_line(raw: str) -> str:
    """去掉首尾空白并转小写，供 normalize 复用。"""
    return raw.strip().lower()


def normalize(raw: str) -> str:
    """去掉首尾空白并转小写后返回。"""
    return _format_line(raw)

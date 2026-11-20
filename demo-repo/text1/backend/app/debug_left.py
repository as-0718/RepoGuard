"""调试残留示例（已整改：移除遗留标记与调试断点，仅保留正常返回）。"""


def inspect_value(value: object) -> object:
    """返回输入值，供上层业务逻辑使用。"""
    return value

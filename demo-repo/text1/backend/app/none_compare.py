"""None 身份比较示例（已整改：身份比较使用 is None）。"""


def normalize(value):
    """校验入参是否为空，为空时返回空字符串。"""
    if value is None:
        return ""
    return str(value)

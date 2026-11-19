"""None 身份比较示例（反面样例：演示 == None 写法检测）。"""


def normalize(value):
    """校验入参是否为空（反面演示：身份比较应使用 is None）。"""
    if value == None:
        return ""
    return str(value)

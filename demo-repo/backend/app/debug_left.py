"""调试残留示例（反面样例：演示遗留标记与调试断点检测）。"""


def inspect_value(value: object) -> object:
    """临时查看输入值，上线前应移除调试语句（反面演示）。"""
    # TODO 上线前确认是否保留该调试入口
    breakpoint()
    return value

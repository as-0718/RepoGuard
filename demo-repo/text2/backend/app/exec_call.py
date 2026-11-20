"""动态执行示例（已整改：不再调用 exec，动作按白名单映射处理）。"""

_ACTIONS = {"refresh": "刷新缓存", "reload": "重新加载配置"}


def run_dynamic(code: str) -> str:
    """按动作名白名单返回对应处理结果，不执行传入的代码字符串。"""
    return _ACTIONS.get(code, "未知动作")

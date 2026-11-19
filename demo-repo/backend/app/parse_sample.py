"""配置解析示例：演示规范的模块说明与函数注释写法。"""


def parse_count(text: str) -> int:
    """把文本解析为非负整数，解析失败或为空时返回 0。"""
    if not text:
        return 0
    return int(text)

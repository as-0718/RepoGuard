"""规范写法对照示例：模块与函数注释齐全，可作为正面参照。"""


def _clean(raw: str) -> str:
    """去除报文首尾空白并转小写，供主流程复用。"""
    return raw.strip().lower()


def normalize(raw: str) -> str:
    """清洗输入文本，返回去除首尾空白的小写结果。"""
    return _clean(raw)

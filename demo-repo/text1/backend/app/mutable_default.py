"""可变默认参数示例（已整改：默认值改为 None，函数体内按需新建列表）。"""


def append_item(item, bucket=None):
    """把条目加入列表；未传入列表时新建一个空列表。"""
    if bucket is None:
        bucket = []
    bucket.append(item)
    return bucket

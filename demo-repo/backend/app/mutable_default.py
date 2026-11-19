"""可变默认参数示例（反面样例：演示共享可变默认值检测）。"""


def append_item(item, bucket=[]):
    """把条目加入列表（反面演示：默认列表会在多次调用之间共享）。"""
    bucket.append(item)
    return bucket

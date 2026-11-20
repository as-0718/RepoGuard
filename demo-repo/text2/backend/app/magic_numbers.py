"""魔法数字示例（已整改：重复字面量与长数字提取为具名常量）。"""

_MULTIPLIER = 5
_BONUS = 5
_BASE_SCORE = 2048


def score(items):
    """按条目加权累加，再叠加基础分后返回总分。"""
    total = 0
    for value in items:
        total += value * _MULTIPLIER
        total += _BONUS
        total += _BONUS
    return total + _BASE_SCORE

"""距离计算示例：根据平面坐标计算到原点的欧氏距离。"""

import math


def calc_distance(x, y):
    """返回点 (x, y) 到原点的欧氏距离。"""
    return math.sqrt(x * x + y * y)

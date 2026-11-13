"""演示用测试文件，展示规范的测试目录与注释写法。"""

import unittest


class DemoTest(unittest.TestCase):
    """演示用例集合。"""

    def test_add(self):
        """验证加法结果。"""
        self.assertEqual(1 + 1, 2)


if __name__ == "__main__":
    unittest.main()
"""规范测试文件对照：位于 backend/tests/ 目录，注释齐全。"""
import unittest


class CleanSampleTest(unittest.TestCase):
    """规范用例集合。"""

    def test_add(self):
        """验证加法结果。"""
        self.assertEqual(1 + 1, 2)

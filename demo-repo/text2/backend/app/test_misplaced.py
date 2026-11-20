"""错放目录的测试文件（反面样例：演示测试文件归属检查）。"""
import unittest


class MisplacedTest(unittest.TestCase):
    """错放目录的用例集合。"""

    def test_ok(self):
        """验证真值断言。"""
        self.assertTrue(True)

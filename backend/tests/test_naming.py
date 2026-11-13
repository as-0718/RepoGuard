from __future__ import annotations

import unittest

from app.core.rules import naming
from app.core.rules.common.config import DEFAULT_CONFIG
from app.core.rules.common.file_io import CheckContext
from app.core.rules.common.models import ChangeEntry, ChangeStatus, IssueLevel

ALLOWED_RULES = {f"naming-{index:03d}" for index in range(1, 7)}


def _rule_ids(findings):
    return {finding.rule_id for finding in findings}


def _check_path(path):
    findings = list(naming.check_naming(path, DEFAULT_CONFIG))
    findings.extend(naming.check_directory(path, DEFAULT_CONFIG))
    return findings


class NamingTest(unittest.TestCase):
    def test_illegal_chars(self):
        for path in ("lab/a:b.c", "lab/a*b.c", "lab/a?.c", "lab/a."):
            with self.subTest(path=path):
                found = naming.check_naming(path, DEFAULT_CONFIG)
                self.assertIn("naming-001", _rule_ids(found))
                item = [finding for finding in found if finding.rule_id == "naming-001"][0]
                self.assertIs(item.level, IssueLevel.MUST_FIX)

    def test_long_name(self):
        long_name = "a" * 119 + ".c"
        short_name = "a" * 118 + ".c"
        self.assertIn("naming-002", _rule_ids(naming.check_naming("lab/" + long_name, DEFAULT_CONFIG)))
        self.assertNotIn("naming-002", _rule_ids(naming.check_naming("lab/" + short_name, DEFAULT_CONFIG)))

    def test_style_advice(self):
        found = naming.check_naming("lab/uart/UART Demo-v2.C", DEFAULT_CONFIG)
        self.assertIn("naming-003", _rule_ids(found))
        item = [finding for finding in found if finding.rule_id == "naming-003"][0]
        self.assertIn("uart_demo_v2.c", item.suggestion)

    def test_chinese_name_advice_only(self):
        found = naming.check_naming("docs/lab03_串口通信实验.md", DEFAULT_CONFIG)
        self.assertIn("naming-004", _rule_ids(found))
        item = [finding for finding in found if finding.rule_id == "naming-004"][0]
        self.assertIs(item.level, IssueLevel.SUGGESTION)
        self.assertIn("docs/lab03_serial_communication.md", item.suggestion)

    def test_wrong_directory_must_fix(self):
        cases = {
            "docs/uart_demo.c": "lab/uart_demo.c",
            "backend/app/a.md": "docs/a.md",
            "lab/test_x.py": "backend/tests/test_x.py",
        }
        for path, target in cases.items():
            with self.subTest(path=path):
                found = naming.check_directory(path, DEFAULT_CONFIG)
                self.assertIn("naming-005", _rule_ids(found))
                item = [finding for finding in found if finding.rule_id == "naming-005"][0]
                self.assertIs(item.level, IssueLevel.MUST_FIX)
                self.assertIn(target.split("/")[-1], item.suggestion)

    def test_root_source_advice(self):
        found = naming.check_directory("uart_demo.c", DEFAULT_CONFIG)
        self.assertIn("naming-006", _rule_ids(found))
        item = found[0]
        self.assertIs(item.level, IssueLevel.SUGGESTION)
        self.assertIn("lab/uart_demo.c", item.suggestion)

    def test_directory_map(self):
        cases = {
            "docs/a.md": None,
            "lab/a.c": None,
            "backend/app/a.py": None,
            "assets/a.png": None,
            "backend/tests/test_a.py": None,
            "src/a.h": None,
            "lab/a.md": "naming-005",
            "backend/a.png": "naming-006",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                rules = _rule_ids(naming.check_directory(path, DEFAULT_CONFIG))
                if expected is None:
                    self.assertFalse(rules, f"{path} 不应产生目录问题，实际：{rules}")
                else:
                    self.assertIn(expected, rules)

    def test_no_extension(self):
        rules = _rule_ids(naming.check_directory("lab/Makefile", DEFAULT_CONFIG))
        self.assertFalse(rules)

    def test_unknown_extension(self):
        rules = _rule_ids(naming.check_directory("lab/a.xyz", DEFAULT_CONFIG))
        self.assertFalse(rules)

    def test_merge_style_issues(self):
        found = naming.check_naming("lab/UART Demo-v2.C", DEFAULT_CONFIG)
        style_rules = [rule for rule in _rule_ids(found) if rule in {"naming-003", "naming-004"}]
        self.assertEqual(len(style_rules), 1)

    def test_merge_directory_issues(self):
        rules = _rule_ids(naming.check_directory("test_x.py", DEFAULT_CONFIG))
        self.assertIn("naming-005", rules)
        self.assertNotIn("naming-006", rules)

    def test_max_four_findings(self):
        entry = ChangeEntry(
            status=ChangeStatus.ADD,
            path="串口" * 60 + ":" + "a" * 120 + ".c",
            line_no=1,
        )
        context = CheckContext(repo_root=__import__("pathlib").Path("."), config=DEFAULT_CONFIG, module_name="naming", snapshot=lambda path: None)
        result = naming.check(entry, context)
        self.assertLessEqual(len(result.findings), 4)

    def test_directory_prefix_boundary(self):
        rules = _rule_ids(naming.check_directory("backendx/a.md", DEFAULT_CONFIG))
        self.assertNotIn("naming-005", rules)

    def test_no_must_fix_for_chinese(self):
        found = _check_path("lab/串口实验.c")
        self.assertFalse([finding for finding in found if finding.level is IssueLevel.MUST_FIX])

    def test_pinyin_hyphen_ok(self):
        found = _check_path("lab/uart/uart-demo.c")
        self.assertFalse([finding for finding in found if finding.level is IssueLevel.MUST_FIX])

    def test_suggestion_has_example(self):
        paths = (
            "lab/uart/UART Demo-v2.C",
            "docs/lab03_串口通信实验.md",
            "docs/uart_demo.c",
            "uart_demo.c",
        )
        for path in paths:
            with self.subTest(path=path):
                found = _check_path(path)
                for item in found:
                    self.assertTrue(item.suggestion.strip())
                    self.assertTrue(("/" in item.suggestion) or ("_" in item.suggestion) or (".c" in item.suggestion))

    def test_deleted_status_no_read(self):
        def explode(path):
            raise AssertionError("命名检查不应读取文件")

        context = CheckContext(repo_root=__import__("pathlib").Path("."), config=DEFAULT_CONFIG, module_name="naming", snapshot=explode)
        entry = ChangeEntry(status=ChangeStatus.DELETE, path="lab/uart_demo.c", line_no=1)
        result = naming.check(entry, context)
        self.assertIsNotNone(result)

    def test_rule_ids_stable(self):
        paths = (
            "lab/a:b.c",
            "lab/" + "a" * 130 + ".c",
            "lab/UART Demo-v2.C",
            "docs/串口.md",
            "docs/uart_demo.c",
            "uart_demo.c",
        )
        for path in paths:
            for rule_id in _rule_ids(_check_path(path)):
                self.assertIn(rule_id, ALLOWED_RULES)


if __name__ == "__main__":
    unittest.main()
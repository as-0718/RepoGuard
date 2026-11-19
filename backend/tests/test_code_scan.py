from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.rules import code_scan
from app.core.rules.common.config import DEFAULT_CONFIG
from app.core.rules.common.file_io import CheckContext, create_snapshot
from app.core.rules.common.models import ChangeEntry, ChangeStatus, IssueLevel


def _context(root: Path) -> CheckContext:
    config = DEFAULT_CONFIG
    return CheckContext(
        repo_root=root,
        config=config,
        module_name="code_scan",
        snapshot=lambda path: create_snapshot(root, path, config),
    )


def _check_file(root: Path, relative: str, content: str | bytes) -> tuple:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    entry = ChangeEntry(status=ChangeStatus.ADD, path=relative, line_no=1)
    return code_scan.check(entry, _context(root)).findings


class CodeScanTest(unittest.TestCase):
    def test_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deleted = ChangeEntry(status=ChangeStatus.DELETE, path="lab/a.py", line_no=1)
            result = code_scan.check(deleted, _context(root))
            self.assertEqual(result.findings, ())
            self.assertEqual(_check_file(root, "docs/a.md", "# 文档\n"), ())

    def test_module_header(self):
        python_without = code_scan.scan_python_source("x = 1\n", "a.py", DEFAULT_CONFIG)
        python_with = code_scan.scan_python_source('"""说明。"""\nx = 1\n', "a.py", DEFAULT_CONFIG)
        c_without = code_scan.scan_c_source("int main(void) { return 0; }\n", "a.c", DEFAULT_CONFIG)
        c_with = code_scan.scan_c_source("/* 文件说明 */\nint main(void) { return 0; }\n", "a.c", DEFAULT_CONFIG)
        self.assertIn("code-001", {item.rule_id for item in python_without})
        self.assertNotIn("code-001", {item.rule_id for item in python_with})
        self.assertIn("code-001", {item.rule_id for item in c_without})
        self.assertNotIn("code-001", {item.rule_id for item in c_with})

    def test_public_function_comment(self):
        python_text = "def foo():\n    return 1\n"
        method_text = "class A:\n    def bar(self):\n        return 1\n"
        c_text = "/* 文件说明 */\nint global_value = 0;\nint main(void) {\n    return 0;\n}\n"
        self.assertIn("code-002", {item.rule_id for item in code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-002", {item.rule_id for item in code_scan.scan_python_source(method_text, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-002", {item.rule_id for item in code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)})

    def test_static_helper_advice(self):
        c_text = (
            "/* 文件说明 */\n"
            "// 主函数\n"
            "int main(void) { return 0; }\n"
            "static int helper(void) {\n"
            "    int a = 1;\n"
            "    return a;\n"
            "}\n"
        )
        findings = code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)
        helper_findings = [item for item in findings if item.rule_id == "code-003"]
        self.assertTrue(helper_findings)
        with_comment = c_text.replace("static int helper", "// helper 说明\nstatic int helper")
        self.assertFalse([item for item in code_scan.scan_c_source(with_comment, "a.c", DEFAULT_CONFIG) if item.rule_id == "code-003"])

    def test_high_risk(self):
        c_text = (
            "/* 文件说明 */\n"
            "// 主函数\n"
            "int main(void) {\n"
            "    char a[10];\n"
            "    char *b = \"x\";\n"
            "    strcpy(a, b);\n"
            "    return 0;\n"
            "}\n"
        )
        python_text = '"""说明。"""\nvalue = eval(user_input)\n'
        shell_text = '"""说明。"""\nimport os\nos.system("rm " + name)\n'
        self.assertIn("code-004", {item.rule_id for item in code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)})
        self.assertIn("code-005", {item.rule_id for item in code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-006", {item.rule_id for item in code_scan.scan_python_source(shell_text, "a.py", DEFAULT_CONFIG)})

    def test_suspicious(self):
        c_text = "/* 文件说明 */\n// 主函数\nint main(void) { while(1) { } for(;;) { } return 0; }\n"
        python_text = '"""说明。"""\nimport subprocess\ntry:\n    pass\nexcept:\n    pass\n'
        self.assertIn("code-007", {item.rule_id for item in code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)})
        self.assertIn("code-007", {item.rule_id for item in code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)})

    def test_line_number(self):
        lines = ["/* 文件说明 */", "// 主函数", "int main(void) {", "    char a[10];"]
        lines.extend(f"    int x{index} = 0;" for index in range(22))
        lines.extend(["    strcpy(a, b);", "    return 0;", "}"])
        text = "\n".join(lines) + "\n"
        findings = [item for item in code_scan.scan_c_source(text, "a.c", DEFAULT_CONFIG) if item.rule_id == "code-004"]
        self.assertTrue(findings)
        self.assertEqual(findings[0].line_no, 27)

    def test_chinese_comment_ok(self):
        c_text = "/* 文件说明 */\n// 主函数\nint main(void) { return 0; }\n"
        python_text = '"""模块说明。"""\ndef foo():\n    """函数说明。"""\n    return 1\n'
        self.assertNotIn("code-002", {item.rule_id for item in code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)})
        self.assertNotIn("code-002", {item.rule_id for item in code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)})

    def test_comment_position(self):
        inside_comment = '"""模块说明。"""\ndef foo():\n    # 只写在函数体内\n    return 1\n'
        blank_between = "/* 文件说明 */\n// 主函数\n\nint main(void) { return 0; }\n"
        docstring_first = '"""模块说明。"""\ndef foo():\n    """函数说明。"""\n    return 1\n'
        self.assertIn("code-002", {item.rule_id for item in code_scan.scan_python_source(inside_comment, "a.py", DEFAULT_CONFIG)})
        self.assertNotIn("code-002", {item.rule_id for item in code_scan.scan_c_source(blank_between, "a.c", DEFAULT_CONFIG)})
        self.assertNotIn("code-002", {item.rule_id for item in code_scan.scan_python_source(docstring_first, "a.py", DEFAULT_CONFIG)})

    def test_header_with_bom_and_blank(self):
        text = "\ufeff\n\n/* 文件说明 */\nint main(void) { return 0; }\n"
        self.assertNotIn("code-001", {item.rule_id for item in code_scan.scan_c_source(text, "a.c", DEFAULT_CONFIG)})

    def test_aggregation(self):
        body = "".join("    strcpy(a, b);\n" for _ in range(6))
        text = "/* 文件说明 */\n// 主函数\nint main(void) {\n" + body + "    return 0;\n}\n"
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "lab/a.c", text)
        code_findings = [item for item in findings if item.rule_id == "code-004"]
        self.assertEqual(len(code_findings), 6)
        self.assertTrue(any("另有" in item.message for item in code_findings))

    def test_comment_string_no_false_positive(self):
        c_text = (
            "/* 文件说明 */\n"
            "// 主函数\n"
            "int main(void) {\n"
            "    // strcpy(a, b);\n"
            "    char *s = \"strcpy(a, b)\";\n"
            "    return 0;\n"
            "}\n"
        )
        python_text = '"""说明。"""\ndef foo():\n    """函数说明 eval(x)"""\n    return 1\n'
        self.assertNotIn("code-004", {item.rule_id for item in code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)})
        self.assertNotIn("code-005", {item.rule_id for item in code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)})

    def test_literal_eval_ok(self):
        text = '"""说明。"""\nimport ast\nvalue = ast.literal_eval(text)\nmodel.eval()\n'
        self.assertNotIn("code-005", {item.rule_id for item in code_scan.scan_python_source(text, "a.py", DEFAULT_CONFIG)})

    def test_subprocess_list_ok(self):
        text = '"""说明。"""\nimport subprocess\nsubprocess.run(["ls"])\n'
        self.assertNotIn("code-006", {item.rule_id for item in code_scan.scan_python_source(text, "a.py", DEFAULT_CONFIG)})

    def test_syntax_error(self):
        text = "def broken(:\n    pass\n"
        self.assertEqual(code_scan.scan_python_source(text, "a.py", DEFAULT_CONFIG), ())

    def test_macro_wrapped_skip(self):
        text = "/* 文件说明 */\n#define FOO(x) do { x; } while (0)\n"
        self.assertNotIn("code-002", {item.rule_id for item in code_scan.scan_c_source(text, "a.c", DEFAULT_CONFIG)})

    def test_no_style_must_fix(self):
        text = '"""说明。"""\nx = 1\nthis_is_a_very_long_line = "a" * 200\n'
        self.assertFalse([item for item in code_scan.scan_python_source(text, "a.py", DEFAULT_CONFIG) if item.level is IssueLevel.MUST_FIX])

    def test_header_downgrade(self):
        text = "/* 文件说明 */\nvoid foo(void) {\n    strcpy(a, b);\n}\n"
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "lab/a.h", text)
        self.assertTrue(findings)
        self.assertFalse([item for item in findings if item.level is IssueLevel.MUST_FIX])

    def test_large_file_skip(self):
        content = b"/* header */\n" + b"a" * (5 * 1024 * 1024 + 10)
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "lab/large.c", content)
        self.assertEqual({item.rule_id for item in findings}, {"code-008"})

    def test_binary_or_encoding_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "lab/binary.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00\x01\x02")
            entry = ChangeEntry(status=ChangeStatus.ADD, path="lab/binary.py", line_no=1)
            result = code_scan.check(entry, _context(root))
        self.assertEqual(result.findings, ())
        self.assertIsNotNone(result.skip_reason)

    def test_comment_marker(self):
        python_text = '"""说明。"""\n# TODO 补充边界单测\ndef foo():\n    return 1\n'
        c_text = "/* 文件说明 */\n// FIXME 处理空指针\nint main(void) { return 0; }\n"
        python_findings = code_scan.scan_python_source(python_text, "a.py", DEFAULT_CONFIG)
        c_findings = code_scan.scan_c_source(c_text, "a.c", DEFAULT_CONFIG)
        self.assertIn("code-009", {item.rule_id for item in python_findings})
        self.assertIn("code-009", {item.rule_id for item in c_findings})
        clean_python = '"""说明。"""\ndef foo():\n    return 1\n'
        self.assertNotIn("code-009", {item.rule_id for item in code_scan.scan_python_source(clean_python, "a.py", DEFAULT_CONFIG)})

    def test_debug_trace(self):
        bp_text = '"""说明。"""\ndef foo():\n    breakpoint()\n    return 1\n'
        pdb_text = '"""说明。"""\nimport pdb\ndef foo():\n    pdb.set_trace()\n    return 1\n'
        self.assertIn("code-010", {item.rule_id for item in code_scan.scan_python_source(bp_text, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-010", {item.rule_id for item in code_scan.scan_python_source(pdb_text, "a.py", DEFAULT_CONFIG)})
        clean = '"""说明。"""\ndef foo():\n    return 1\n'
        self.assertNotIn("code-010", {item.rule_id for item in code_scan.scan_python_source(clean, "a.py", DEFAULT_CONFIG)})

    def test_bug_patterns(self):
        mutable = '"""说明。"""\ndef append(item, bucket=[]):\n    """追加到列表。"""\n    bucket.append(item)\n    return bucket\n'
        none_cmp = '"""说明。"""\ndef normalize(value):\n    """归一化。"""\n    if value == None:\n        return ""\n    return str(value)\n'
        empty = '"""说明。"""\ndef stub():\n    """预留接口。"""\n    pass\n'
        self.assertIn("code-011", {item.rule_id for item in code_scan.scan_python_source(mutable, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-012", {item.rule_id for item in code_scan.scan_python_source(none_cmp, "a.py", DEFAULT_CONFIG)})
        self.assertIn("code-013", {item.rule_id for item in code_scan.scan_python_source(empty, "a.py", DEFAULT_CONFIG)})
        clean = '"""说明。"""\ndef normalize(value):\n    """归一化。"""\n    if value is None:\n        return ""\n    return str(value)\n'
        clean_ids = {item.rule_id for item in code_scan.scan_python_source(clean, "a.py", DEFAULT_CONFIG)}
        self.assertNotIn("code-011", clean_ids)
        self.assertNotIn("code-012", clean_ids)
        self.assertNotIn("code-013", clean_ids)

    def test_no_execution(self):
        text = '"""说明。"""\nraise RuntimeError("不应被执行")\nopen("side_effect.txt", "w")\n'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _check_file(root, "lab/danger.py", text)
            self.assertFalse((root / "side_effect.txt").exists())


if __name__ == "__main__":
    unittest.main()
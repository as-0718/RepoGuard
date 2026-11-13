from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.rules import link_check
from app.core.rules.common.config import DEFAULT_CONFIG
from app.core.rules.common.file_io import CheckContext, create_snapshot
from app.core.rules.common.models import ChangeEntry, ChangeStatus, IssueLevel


def _findings(text: str) -> tuple:
    links = link_check.extract_links(link_check.strip_code_blocks(text))
    return link_check.validate_links(links, "docs/sample.md", DEFAULT_CONFIG)


def _check_md(root: Path, relative: str, content: str) -> tuple:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    entry = ChangeEntry(status=ChangeStatus.ADD, path=relative, line_no=1)
    context = CheckContext(
        repo_root=root,
        config=DEFAULT_CONFIG,
        module_name="link_check",
        snapshot=lambda item: create_snapshot(root, item, DEFAULT_CONFIG),
    )
    return link_check.check(entry, context)


class LinkCheckTest(unittest.TestCase):
    def test_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            deleted = ChangeEntry(status=ChangeStatus.DELETE, path="docs/a.md", line_no=1)
            context = CheckContext(root, DEFAULT_CONFIG, "link_check", lambda path: create_snapshot(root, path, DEFAULT_CONFIG))
            self.assertEqual(link_check.check(deleted, context).findings, ())
            self.assertEqual(_check_md(root, "lab/a.txt", "[说明]()").findings, ())

    def test_extract_types(self):
        text = (
            "[行内](./a.md)\n"
            "![图片](./b.png)\n"
            "[引用][ref1]\n"
            "[ref1]: ./c.md\n"
            "https://example.com\n"
        )
        kinds = {link.kind for link in link_check.extract_links(text)}
        self.assertEqual(kinds, {"inline", "image", "reference", "definition", "bare"})

    def test_empty_target(self):
        self.assertIn("link-001", {item.rule_id for item in _findings("[说明]()")})

    def test_unclosed(self):
        self.assertIn("link-002", {item.rule_id for item in _findings("[说明](./lab03.md")})

    def test_missing_definition(self):
        self.assertIn("link-003", {item.rule_id for item in _findings("[说明][ref1]")})
        defined = "[说明][ref1]\n\n[ref1]: ./a.md\n"
        self.assertNotIn("link-003", {item.rule_id for item in _findings(defined)})

    def test_absolute_path(self):
        findings = _findings("[说明](file:///C:/Users/student/lab03.md)")
        self.assertIn("link-004", {item.rule_id for item in findings})
        self.assertIs([item for item in findings if item.rule_id == "link-004"][0].level, IssueLevel.SUGGESTION)

    def test_space_in_target(self):
        self.assertIn("link-005", {item.rule_id for item in _findings("[说明](./lab 03.md)")})
        self.assertNotIn("link-005", {item.rule_id for item in _findings("[说明](<./lab 03.md>)")})

    def test_protocol_advice(self):
        self.assertIn("link-006", {item.rule_id for item in _findings("[说明](http://example.com)")})
        self.assertIn("link-006", {item.rule_id for item in _findings("[说明](http://127.0.0.1/a.md)")})
        self.assertIn("link-006", {item.rule_id for item in _findings("[](./a.md)")})

    def test_line_and_excerpt(self):
        text = "\n" * 11 + "[说明]()\n"
        findings = _findings(text)
        self.assertEqual(findings[0].line_no, 12)
        self.assertLessEqual(len(findings[0].excerpt or ""), 60)

    def test_chinese_anchor_ok(self):
        findings = _findings("[实验](./实验指导.md#第三部分)")
        self.assertFalse([item for item in findings if item.level is IssueLevel.MUST_FIX])
        self.assertIn("link-007", {item.rule_id for item in findings})

    def test_reference_defined_later(self):
        text = "[说明][ref1]\n\n[ref1]: ./a.md\n"
        self.assertNotIn("link-003", {item.rule_id for item in _findings(text)})

    def test_many_links(self):
        content = "".join(f"[链接{index}](./a.md)\n" for index in range(201))
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_md(Path(temp), "docs/many.md", content).findings
        self.assertIn("link-008", {item.rule_id for item in findings})
        content_200 = "".join(f"[链接{index}](./a.md)\n" for index in range(200))
        with tempfile.TemporaryDirectory() as temp:
            findings_200 = _check_md(Path(temp), "docs/many.md", content_200).findings
        self.assertNotIn("link-008", {item.rule_id for item in findings_200})

    def test_multiline_link(self):
        self.assertIn("link-002", {item.rule_id for item in _findings("[说明](\n./a.md)")})

    def test_same_line_dedup(self):
        findings = _findings("[说明](http://example.com/a b)")
        line_findings = [item for item in findings if item.line_no == 1]
        self.assertEqual(len(line_findings), 1)
        self.assertEqual(line_findings[0].rule_id, "link-005")

    def test_rule_aggregation(self):
        text = "".join("[]()\n" for _ in range(6))
        findings = [item for item in _findings(text) if item.rule_id == "link-001"]
        self.assertEqual(len(findings), 6)
        self.assertTrue(any("另有" in item.message for item in findings))

    def test_skip_code_block(self):
        text = (
            "```\n[说明]()\n```\n"
            "~~~\n[说明]()\n~~~\n"
            "`[说明]()`\n"
        )
        self.assertEqual(_findings(text), ())

    def test_shortcut_reference_no_false_positive(self):
        self.assertEqual(_findings("[标识]"), ())

    def test_no_network(self):
        with patch("socket.socket", side_effect=AssertionError("不应发起网络请求")):
            findings = _findings("[说明](https://example.com/a.md)")
        self.assertIsNotNone(findings)

    def test_outside_repo(self):
        findings = _findings("[说明](../outside.md)")
        self.assertIn("link-007", {item.rule_id for item in findings})
        self.assertIs([item for item in findings if item.rule_id == "link-007"][0].level, IssueLevel.SUGGESTION)

    def test_binary_or_encoding_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docs/binary.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x00\x01\x02")
            entry = ChangeEntry(status=ChangeStatus.ADD, path="docs/binary.md", line_no=1)
            context = CheckContext(root, DEFAULT_CONFIG, "link_check", lambda item: create_snapshot(root, item, DEFAULT_CONFIG))
            result = link_check.check(entry, context)
        self.assertEqual(result.findings, ())
        self.assertIsNotNone(result.skip_reason)

    def test_no_links(self):
        self.assertEqual(_findings("这是一段没有链接的说明。\n"), ())


if __name__ == "__main__":
    unittest.main()
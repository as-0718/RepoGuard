from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.rules.common.manifest import (
    ManifestReadError,
    has_escaping_segments,
    load_manifest_text,
    merge_entries,
    normalize_path,
    parse_manifest,
    parse_manifest_line,
)
from app.core.rules.common.models import ChangeEntry, ChangeStatus, UnparsedLine


class ManifestTest(unittest.TestCase):
    def test_parse_format(self):
        result = parse_manifest("A path/a.md\nA\t path/b.md\n   A   path/c.md\n")
        self.assertEqual([entry.path for entry in result.entries], ["path/a.md", "path/b.md", "path/c.md"])

    def test_lowercase_status(self):
        result = parse_manifest("a a.md\nm b.md\nd c.md\n")
        self.assertEqual(
            [entry.status for entry in result.entries],
            [ChangeStatus.ADD, ChangeStatus.MODIFY, ChangeStatus.DELETE],
        )

    def test_unknown_status(self):
        result = parse_manifest("X notes/a.md\n1 a.md\n")
        self.assertEqual(len(result.unparsed_lines), 2)
        for item in result.unparsed_lines:
            self.assertIn("未知状态", item.reason)

    def test_missing_path(self):
        result = parse_manifest("M\nM   \n")
        self.assertEqual(len(result.unparsed_lines), 2)
        for item in result.unparsed_lines:
            self.assertEqual(item.reason, "缺少文件路径")

    def test_ignore_blank_comment(self):
        result = parse_manifest("\n   \n# 注释\n   # 缩进注释\n")
        self.assertEqual(result.entries, ())
        self.assertEqual(result.unparsed_lines, ())

    def test_path_normalize(self):
        self.assertEqual(normalize_path(".\\lab\\uart\\uart_demo.c"), "lab/uart/uart_demo.c")
        self.assertEqual(normalize_path("a//b"), "a/b")
        self.assertEqual(normalize_path("././a.md"), "a.md")
        self.assertEqual(normalize_path("docs/实验.MD"), "docs/实验.MD")

    def test_raw_truncate(self):
        item = parse_manifest_line("A " + "a" * 600, 1)
        self.assertIsNotNone(item)
        self.assertEqual(len(item.raw), 500)

    def test_line_no(self):
        result = parse_manifest("\n# 注释\nA docs/a.md\n")
        self.assertEqual(result.entries[0].line_no, 3)

    def test_duplicate_merge(self):
        merged = merge_entries(parse_manifest("A lab/a.c\nM lab/a.c\n").entries)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].status, ChangeStatus.MODIFY)
        self.assertEqual(merged[0].duplicate_count, 2)
        self.assertEqual(merged[0].line_no, 1)

    def test_merge_order(self):
        merged = merge_entries(parse_manifest("A b.md\nA a.md\nM b.md\n").entries)
        self.assertEqual([entry.path for entry in merged], ["b.md", "a.md"])

    def test_entry_contract(self):
        with self.assertRaises(ValueError):
            ChangeEntry(status=ChangeStatus.ADD, path="", line_no=1)
        absolute = parse_manifest_line("A /etc/passwd", 1)
        drive = parse_manifest_line("A C:\\Windows\\win.ini", 1)
        self.assertTrue(absolute.has_illegal_path)
        self.assertTrue(drive.has_illegal_path)

    def test_has_escaping_segments(self):
        self.assertTrue(has_escaping_segments(normalize_path("../a.md")))
        self.assertTrue(has_escaping_segments(normalize_path("a/../../b")))
        self.assertTrue(has_escaping_segments(normalize_path("a/../b")))
        self.assertFalse(has_escaping_segments(normalize_path("a/b.md")))

    def test_no_fs_access_on_invalid(self):
        with patch("builtins.open") as open_mock, patch("os.stat") as stat_mock:
            parse_manifest("X notes/a.md\nM\nA a.md\n")
        self.assertEqual(open_mock.call_count, 0)
        self.assertEqual(stat_mock.call_count, 0)

    def test_load_manifest_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            utf8_file = root / "utf8.txt"
            utf8_file.write_text("A 中文.md\n", encoding="utf-8")
            self.assertIn("中文", load_manifest_text(utf8_file))

            bom_file = root / "bom.txt"
            bom_file.write_bytes(b"\xef\xbb\xbfA a.md\n")
            self.assertEqual(load_manifest_text(bom_file).strip(), "A a.md")

            gb_file = root / "gb.txt"
            gb_file.write_bytes("A 中文.md\n".encode("gb18030"))
            self.assertIn("中文", load_manifest_text(gb_file))

            with self.assertRaises(ManifestReadError):
                load_manifest_text(root / "missing.txt")
            with self.assertRaises(ManifestReadError):
                load_manifest_text(root)

    def test_crlf(self):
        lf_result = parse_manifest("A a.md\nM b.md\n")
        crlf_result = parse_manifest("A a.md\r\nM b.md\r\n")
        self.assertEqual(
            [entry.path for entry in lf_result.entries],
            [entry.path for entry in crlf_result.entries],
        )

    def test_unparsed_line_type(self):
        item = parse_manifest_line("X a.md", 1)
        self.assertIsInstance(item, UnparsedLine)


if __name__ == "__main__":
    unittest.main()
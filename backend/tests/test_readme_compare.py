from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.readme.compare import (

    diff_toc,
    locate_readme,
    locate_toc_block,
    parse_toc_entries,
    render_replacement_block,
    validate_readme_path,
)
from app.readme.index import build_index, render_index_markdown
from app.readme.models import (
    Confidence,
    DemoProject,
    DemoScanResult,
    DocEntry,
    ReadmeDiff,
    TitleSource,
    sort_diffs,
)
from app.readme.service import run_readme_scan


def _doc(path: str, title: str | None = None) -> DocEntry:
    return DocEntry(path, title or path, TitleSource.ATX, 1)


class ReadmeCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_toc_marker_block_range(self) -> None:
        text = "# 标题\n  <!-- toc -->  \n- [A](a.md)\n  <!-- /toc -->  \n## 其他\n"
        block = locate_toc_block(text)
        self.assertIsNotNone(block)
        self.assertEqual((block.start_line, block.end_line), (1, 3))
        self.assertEqual(block.marker_kind, "TOC")
        self.assertIn("<!-- toc -->", block.lines[0])

    def test_begin_end_marker_block_range(self) -> None:
        text = "<!-- BEGIN TOC -->\n- [A](a.md)\n<!-- END TOC -->\n"
        block = locate_toc_block(text)
        self.assertIsNotNone(block)
        self.assertEqual((block.start_line, block.end_line), (0, 2))
        self.assertEqual(block.marker_kind, "BEGIN_TOC")

    def test_heading_block_range(self) -> None:
        text = "## 目录\n- [A](a.md)\n## 其他\n内容\n"
        block = locate_toc_block(text)
        self.assertIsNotNone(block)
        self.assertEqual((block.start_line, block.end_line), (0, 1))
        self.assertEqual(block.marker_kind, "heading")
        self.assertEqual(block.heading_level, 2)

        nested = "### 文档目录\n- [A](a.md)\n## 其他\n"
        block = locate_toc_block(nested)
        self.assertIsNotNone(block)
        self.assertEqual(block.end_line, 1)

    def test_block_not_found_and_full_replacement(self) -> None:
        self.assertIsNone(locate_toc_block("# 标题\n没有目录\n"))
        index = build_index([_doc("a.md", "A")], DemoScanResult())
        replacement = render_replacement_block(index)
        self.assertEqual(replacement, render_index_markdown(index))
        self.assertIn("[A](a.md)", replacement)

    def test_diff_added(self) -> None:
        block = locate_toc_block("<!-- TOC -->\n- [A](a.md)\n<!-- /TOC -->")
        index = build_index([_doc("a.md", "A"), _doc("b.md", "B")], DemoScanResult())
        diffs = diff_toc(block, index)
        added = next(item for item in diffs if item.change_type == "新增")
        self.assertEqual(added.path, "b.md")
        self.assertIsNone(added.old_title)
        self.assertIsNone(added.old_position)

    def test_diff_removed(self) -> None:
        block = locate_toc_block("<!-- TOC -->\n- [A](a.md)\n- [B](b.md)\n<!-- /TOC -->")
        index = build_index([_doc("a.md", "A")], DemoScanResult())
        diffs = diff_toc(block, index)
        removed = next(item for item in diffs if item.change_type == "删除")
        self.assertEqual(removed.path, "b.md")
        self.assertIsNone(removed.new_title)
        self.assertIsNone(removed.new_position)

    def test_diff_moved(self) -> None:
        block = locate_toc_block("<!-- TOC -->\n    - [A](a.md)\n<!-- /TOC -->")
        index = build_index([_doc("a.md", "A")], DemoScanResult())
        diffs = diff_toc(block, index)
        self.assertEqual([item.change_type for item in diffs], ["移动"])
        self.assertEqual(diffs[0].path, "a.md")

    def test_diff_title_changed(self) -> None:
        block = locate_toc_block("<!-- TOC -->\n- [旧标题](a.md)\n<!-- /TOC -->")
        index = build_index([_doc("a.md", "新标题")], DemoScanResult())
        diffs = diff_toc(block, index)
        self.assertEqual([item.change_type for item in diffs], ["标题变化"])
        self.assertEqual(diffs[0].old_title, "旧标题")
        self.assertEqual(diffs[0].new_title, "新标题")

    def test_moved_and_title_changed_are_two_entries(self) -> None:
        block = locate_toc_block("<!-- TOC -->\n    - [旧标题](a.md)\n<!-- /TOC -->")
        index = build_index([_doc("a.md", "新标题")], DemoScanResult())
        diffs = diff_toc(block, index)
        self.assertEqual([item.change_type for item in diffs], ["移动", "标题变化"])

    def test_diff_sort_order(self) -> None:
        diffs = (
            ReadmeDiff("标题变化", "z.md", "旧", "新", 1, 1),
            ReadmeDiff("新增", "b.md", None, "B", None, 2),
            ReadmeDiff("删除", "a.md", "A", None, 3, None),
            ReadmeDiff("移动", "c.md", "C", "C", 4, 4),
            ReadmeDiff("新增", "a2.md", None, "A2", None, 5),
        )
        ordered = sort_diffs(diffs)
        self.assertEqual(
            [(item.change_type, item.path) for item in ordered],
            [("新增", "a2.md"), ("新增", "b.md"), ("删除", "a.md"), ("移动", "c.md"), ("标题变化", "z.md")],
        )

    def test_replacement_block_matches_index(self) -> None:
        index = build_index(
            [_doc("a.md", "A"), _doc("b.md", "B")],
            DemoScanResult(confirmed=(DemoProject("lab/uart", Confidence.CONFIRMED),)),
        )
        body = render_index_markdown(index)
        toc = locate_toc_block("<!-- TOC -->\n<!-- /TOC -->")
        replacement = render_replacement_block(index, toc)
        self.assertEqual(replacement, "<!-- TOC -->\n\n" + body + "\n\n<!-- /TOC -->")
        self.assertIn("[B](b.md)", replacement)
        self.assertIn("[uart/](lab/uart/)", replacement)
        self.assertNotIn("[不存在](missing.md)", replacement)

        heading = locate_toc_block("## 目录\n")
        heading_replacement = render_replacement_block(index, heading)
        self.assertTrue(heading_replacement.startswith("## 目录\n\n"))
        self.assertIn(body, heading_replacement)

    def test_readme_is_not_modified(self) -> None:
        readme = self._write(
            "README.md",
            "# 根\n\n<!-- TOC -->\n- [根 README](README.md)\n<!-- /TOC -->\n",
        )
        before_hash = hashlib.sha256(readme.read_bytes()).hexdigest()
        before_mtime = readme.stat().st_mtime_ns
        located = locate_readme(self.root)
        self.assertEqual(located, readme.resolve())
        text = readme.read_text(encoding="utf-8")
        block = locate_toc_block(text)
        index = build_index([_doc("README.md", "根 README")], DemoScanResult())
        diff_toc(block, index)
        render_replacement_block(index, block)
        self.assertEqual(hashlib.sha256(readme.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(readme.stat().st_mtime_ns, before_mtime)

    def test_external_links_are_ignored(self) -> None:
        text = (
            "<!-- TOC -->\n"
            "- [外链](https://example.com)\n"
            "- [邮件](mailto:a@example.com)\n"
            "- [锚点](#top)\n"
            "- [绝对](/abs.md)\n"
            "- [盘符](C:/x.md)\n"
            "- [本地](a.md)\n"
            "<!-- /TOC -->"
        )
        entries = parse_toc_entries(locate_toc_block(text))
        self.assertEqual([item.path for item in entries], ["a.md"])

    def test_readme_missing_is_undetermined(self) -> None:
        report = run_readme_scan(self.root)
        self.assertFalse(report.readme_found)
        self.assertIsNone(report.readme_path)
        self.assertTrue(any("未找到 README" in item.reason for item in report.undetermined))
        self.assertIn("## 文档索引", report.replacement_block)

    def test_readme_outside_root_is_rejected(self) -> None:
        outside = self.root.parent / "outside-readme.md"
        outside.write_text("# 外部\n", encoding="utf-8")
        try:
            located, error = validate_readme_path(self.root, outside)
            self.assertIsNone(located)
            self.assertIn("仓库根内", error or "")
        finally:
            outside.unlink(missing_ok=True)

    def test_readme_lookup_is_case_insensitive(self) -> None:
        upper_root = self.root / "upper"
        lower_root = self.root / "lower"
        upper_root.mkdir()
        lower_root.mkdir()
        (upper_root / "README.md").write_text("# 上\n", encoding="utf-8")
        (lower_root / "readme.md").write_text("# 下\n", encoding="utf-8")
        self.assertEqual(locate_readme(upper_root), (upper_root / "README.md").resolve())
        self.assertEqual(locate_readme(lower_root), (lower_root / "readme.md").resolve())


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.readme.models import TitleSource
from app.readme.scanner import (
    classify_demo_directory,
    extract_markdown_title,
    is_test_file,
    scan_demo_projects,
    scan_documents,
)


class ReadmeScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write(self, relative: str, content: str, encoding: str = "utf-8") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode(encoding))
        return path

    def test_extract_atx_title(self) -> None:
        result = extract_markdown_title("# 串口通信实验\n正文\n", "docs/lab03.md")
        self.assertEqual(result.title, "串口通信实验")
        self.assertEqual(result.source, TitleSource.ATX)
        self.assertEqual(result.line_no, 1)

    def test_title_falls_back_to_filename(self) -> None:
        result = extract_markdown_title("正文没有标题\n", "docs/note.md")
        self.assertEqual(result.title, "note")
        self.assertEqual(result.source, TitleSource.FALLBACK_FILENAME)
        self.assertIsNone(result.line_no)

    def test_yaml_front_matter_is_skipped(self) -> None:
        text = "---\ntitle: 示例\n# 假标题\n---\n# 真正标题\n"
        result = extract_markdown_title(text, "docs/a.md")
        self.assertEqual(result.title, "真正标题")
        self.assertEqual(result.line_no, 5)

    def test_unclosed_front_matter_is_treated_as_content(self) -> None:
        result = extract_markdown_title("---\n# 未闭合标题\n", "docs/a.md")
        self.assertEqual(result.title, "未闭合标题")
        self.assertEqual(result.source, TitleSource.ATX)

    def test_fenced_code_blocks_are_skipped(self) -> None:
        backtick = "```\n# 代码标题\n```\n# 正文标题\n"
        tilde = "~~~\n# 波浪代码标题\n~~~\n# 波浪正文标题\n"
        self.assertEqual(extract_markdown_title(backtick, "a.md").title, "正文标题")
        self.assertEqual(extract_markdown_title(tilde, "a.md").title, "波浪正文标题")

    def test_html_comments_are_skipped(self) -> None:
        text = "<!--\n# 注释标题\n-->\n# 正文标题\n"
        self.assertEqual(extract_markdown_title(text, "a.md").title, "正文标题")

    def test_h1_has_priority_over_earlier_h2(self) -> None:
        result = extract_markdown_title("## 二级标题\n# 一级标题\n", "a.md")
        self.assertEqual(result.title, "一级标题")
        self.assertEqual(result.line_no, 2)

    def test_hash_without_space_is_not_a_heading(self) -> None:
        result = extract_markdown_title("#标题\n", "a.md")
        self.assertEqual(result.title, "a")
        self.assertEqual(result.source, TitleSource.FALLBACK_FILENAME)

    def test_inline_code_backticks_are_removed(self) -> None:
        result = extract_markdown_title("# 使用 `uart` 实验\n", "a.md")
        self.assertEqual(result.title, "使用 uart 实验")

    def test_long_title_is_truncated(self) -> None:
        result = extract_markdown_title("# " + "x" * 250 + "\n", "a.md")
        self.assertEqual(len(result.title), 200)
        self.assertTrue(result.truncated)

    def test_gb18030_document_title_is_readable(self) -> None:
        self._write("docs/gb.md", "# 串口通信实验\n", encoding="gb18030")
        entries = scan_documents(self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "串口通信实验")
        self.assertEqual(entries[0].title_source, TitleSource.ATX)

    def test_empty_and_whitespace_documents_fall_back(self) -> None:
        self._write("empty.md", "")
        self._write("space.md", "   \n\n")
        entries = {entry.path: entry for entry in scan_documents(self.root)}
        self.assertEqual(entries["empty.md"].title, "empty")
        self.assertEqual(entries["space.md"].title, "space")
        self.assertEqual(entries["empty.md"].title_source, TitleSource.FALLBACK_FILENAME)

    def test_demo_confirmed_by_entry_file(self) -> None:
        status, evidence = classify_demo_directory("demoA", ["main.py"])
        self.assertEqual(status, "confirmed")
        self.assertIn("main.py", evidence)

    def test_demo_confirmed_by_build_file(self) -> None:
        status, evidence = classify_demo_directory("proj", ["pom.xml", "Util.java"])
        self.assertEqual(status, "confirmed")
        self.assertIn("pom.xml", evidence)

    def test_demo_suspected_by_demo_name(self) -> None:
        status, evidence = classify_demo_directory("lab/uart", ["uart_demo.c"])
        self.assertEqual(status, "suspected")
        self.assertTrue(any("demo/example/sample/tutorial" in item for item in evidence))

    def test_demo_suspected_by_two_sources_and_readme(self) -> None:
        status, evidence = classify_demo_directory("pkg", ["a.py", "b.py", "README.md"])
        self.assertEqual(status, "suspected")
        self.assertIn("源码文件 2 个", evidence)
        self.assertIn("README.md", evidence)

    def test_demo_undetermined_for_single_source(self) -> None:
        status, evidence = classify_demo_directory("pkg", ["util.c"])
        self.assertEqual(status, "undetermined")
        self.assertTrue(any("只有 1 个源码文件" in item for item in evidence))

    def test_excluded_directories_are_not_demos(self) -> None:
        for name in ("tests", "test", "assets", "docs", "notes"):
            status, _ = classify_demo_directory(name, ["main.py"])
            self.assertEqual(status, "none", name)

    def test_test_files_are_not_source_files(self) -> None:
        for name in ("test_demo.py", "demo_test.py", "x.test.js", "x.spec.js"):
            self.assertTrue(is_test_file(name), name)
        status, _ = classify_demo_directory("pkg", ["test_demo.py"])
        self.assertEqual(status, "none")

    def test_root_directory_is_not_demo_candidate(self) -> None:
        self._write("main.py", "print(1)\n")
        result = scan_demo_projects(self.root)
        self.assertEqual(result.confirmed, ())
        self.assertEqual(result.suspected, ())
        self.assertEqual(result.undetermined, ())


if __name__ == "__main__":
    unittest.main()
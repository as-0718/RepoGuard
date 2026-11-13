from __future__ import annotations

import unittest

from app.readme.index import anchor_slug, build_index, render_index_markdown, render_link_target
from app.readme.models import (
    Confidence,
    DemoProject,
    DemoScanResult,
    DocEntry,
    TitleSource,
)


def _doc(path: str, title: str | None = None) -> DocEntry:
    return DocEntry(path, title or path, TitleSource.ATX, 1)


class ReadmeIndexTests(unittest.TestCase):
    def test_relative_paths_have_no_absolute_prefix(self) -> None:
        index = build_index([_doc("docs/x.md", "X")], DemoScanResult())
        rendered = render_index_markdown(index)
        self.assertIn("[X](docs/x.md)", rendered)
        self.assertNotIn("\\", rendered)
        self.assertNotIn(":/", rendered)

    def test_space_path_is_wrapped_in_angle_brackets(self) -> None:
        index = build_index([_doc("docs/lab 03.md", "实验三")], DemoScanResult())
        self.assertIn("[实验三](<docs/lab 03.md>)", render_index_markdown(index))

    def test_chinese_path_is_not_percent_encoded(self) -> None:
        index = build_index([_doc("docs/lab03_串口通信实验.md", "串口通信实验")], DemoScanResult())
        rendered = render_index_markdown(index)
        self.assertIn("docs/lab03_串口通信实验.md", rendered)
        self.assertNotIn("%E4", rendered)

    def test_anchor_slug_and_existing_heading_anchor(self) -> None:
        self.assertEqual(anchor_slug("A  B"), "a-b")
        self.assertEqual(anchor_slug("中文 标题!"), "中文-标题")
        with_anchor = build_index(
            [_doc("docs/x.md", "X")],
            DemoScanResult(),
            anchors={"docs": "docs-anchor"},
        )
        directory = next(item for item in with_anchor.document_section.items if item.kind == "directory")
        self.assertEqual(directory.anchor, "docs-anchor")

        without_anchor = build_index([_doc("docs/x.md", "X")], DemoScanResult())
        directory = next(item for item in without_anchor.document_section.items if item.kind == "directory")
        self.assertIsNone(directory.anchor)

    def test_sorting_directories_before_documents(self) -> None:
        index = build_index(
            [_doc("b.md", "B"), _doc("a/b.md", "AB"), _doc("a/a.md", "AA")],
            DemoScanResult(),
        )
        paths = [item.path for item in index.document_section.items]
        self.assertEqual(paths, ["a/", "b.md", "a/a.md", "a/b.md"])

    def test_duplicate_directories_are_deduplicated(self) -> None:
        index = build_index([_doc("a/x.md", "X"), _doc("a/y.md", "Y")], DemoScanResult())
        directories = [item for item in index.document_section.items if item.kind == "directory"]
        self.assertEqual([item.path for item in directories], ["a/"])

    def test_same_title_is_not_merged(self) -> None:
        index = build_index([_doc("a/same.md", "Same"), _doc("b/same.md", "Same")], DemoScanResult())
        documents = [item for item in index.document_section.items if item.kind == "document"]
        self.assertEqual(len(documents), 2)
        self.assertEqual({item.title for item in documents}, {"Same"})
        self.assertEqual({item.link for item in documents}, {"a/same.md", "b/same.md"})

    def test_confirmed_demos_precede_suspected_demos(self) -> None:
        demos = DemoScanResult(
            confirmed=(DemoProject("z/demo", Confidence.CONFIRMED),),
            suspected=(DemoProject("a/demo", Confidence.SUSPECTED),),
        )
        index = build_index([], demos)
        self.assertEqual([item.path for item in index.demo_section.items], ["z/demo/", "a/demo/"])

    def test_empty_directory_is_omitted(self) -> None:
        index = build_index([], DemoScanResult())
        self.assertEqual(index.item_count, 0)
        self.assertFalse(any(item.kind == "directory" for item in index.all_items()))

    def test_empty_section_uses_placeholder(self) -> None:
        rendered = render_index_markdown(build_index([], DemoScanResult()))
        self.assertIn("## 文档索引\n（无）", rendered)
        self.assertIn("## Demo 工程\n（无）", rendered)

    def test_root_readme_is_marked(self) -> None:
        index = build_index([_doc("README.md", "任意标题")], DemoScanResult())
        item = index.document_section.items[0]
        self.assertEqual(item.title, "根 README")
        self.assertEqual(item.path, "README.md")
        self.assertEqual(index.root_readme_path, "README.md")

    def test_markers_are_optional(self) -> None:
        index = build_index([], DemoScanResult())
        self.assertNotIn("<!-- TOC -->", render_index_markdown(index))
        self.assertIn("<!-- TOC -->", render_index_markdown(index, with_markers=True))
        self.assertIn("<!-- /TOC -->", render_index_markdown(index, with_markers=True))

    def test_document_depth_matches_path(self) -> None:
        index = build_index([_doc("a.md", "A"), _doc("a/b.md", "B")], DemoScanResult())
        documents = {item.path: item for item in index.document_section.items if item.kind == "document"}
        self.assertEqual(documents["a.md"].depth, 0)
        self.assertEqual(documents["a/b.md"].depth, 1)

    def test_demo_link_keeps_trailing_slash(self) -> None:
        index = build_index([], DemoScanResult(confirmed=(DemoProject("lab/uart", Confidence.CONFIRMED),)))
        item = index.demo_section.items[0]
        self.assertEqual(item.path, "lab/uart/")
        self.assertEqual(item.link, "lab/uart/")
        self.assertIn("[uart/](lab/uart/)", render_index_markdown(index))
        self.assertEqual(render_link_target("lab/uart", is_directory=True), "lab/uart/")


if __name__ == "__main__":
    unittest.main()
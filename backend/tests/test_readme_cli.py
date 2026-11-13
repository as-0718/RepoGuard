from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.readme.cli import build_arg_parser, main


MATCHING_README = """# 根 README

<!-- TOC -->

## 文档索引
- [根 README](README.md)

## Demo 工程
（无）

<!-- /TOC -->
"""


class ReadmeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write(self, relative: str, content: str = "x") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _matching_repo(self) -> None:
        self._write("README.md", MATCHING_README)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_exit_code_zero_without_diff_or_undetermined(self) -> None:
        self._matching_repo()
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("README 目录生成报告", stdout)

    def test_exit_code_one_when_diff_exists(self) -> None:
        self._matching_repo()
        self._write("docs/a.md", "# A\n")
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("新增", stdout)

    def test_exit_code_two_for_invalid_root(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root / "missing")])
        self.assertEqual(code, 2)
        self.assertIn("输入存在错误", stdout)

    def test_readme_outside_root_results_in_input_error(self) -> None:
        outside = self.root.parent / "external-readme.md"
        outside.write_text("# 外部\n", encoding="utf-8")
        try:
            code, stdout, _ = self._run(["--repo", str(self.root), "--readme", str(outside)])
            self.assertEqual(code, 2)
            self.assertIn("输入存在错误", stdout)
        finally:
            outside.unlink(missing_ok=True)

    def test_exit_code_three_when_toc_block_missing(self) -> None:
        self._write("README.md", "# 根\n\n正文没有目录区块\n")
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 3)
        self.assertIn("未识别", stdout)

    def test_default_behavior_locates_and_compares_readme(self) -> None:
        self._matching_repo()
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("README：README.md", stdout)
        self.assertIn("目录区块：已识别 TOC", stdout)

    def test_output_outside_repository_is_written(self) -> None:
        self._matching_repo()
        with TemporaryDirectory() as outside:
            target = Path(outside) / "readme.json"
            code, stdout, _ = self._run(
                ["--repo", str(self.root), "--format", "json", "--output", str(target)]
            )
            self.assertEqual(code, 0)
            self.assertTrue(target.exists())
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["scan_root"], self.root.name)
            self.assertIn("format_version", stdout)

    def test_output_inside_repository_is_rejected(self) -> None:
        self._matching_repo()
        target = self.root / "readme.json"
        code, stdout, _ = self._run(["--repo", str(self.root), "--output", str(target)])
        self.assertEqual(code, 2)
        self.assertIn("仓库之外", stdout)
        self.assertFalse(target.exists())

    def test_output_pointing_to_readme_is_rejected(self) -> None:
        readme = self._write("README.md", MATCHING_README)
        before = readme.read_text(encoding="utf-8")
        code, stdout, _ = self._run(["--repo", str(self.root), "--output", str(readme)])
        self.assertEqual(code, 2)
        self.assertIn("仓库之外", stdout)
        self.assertEqual(readme.read_text(encoding="utf-8"), before)

    def test_help_text_is_chinese_and_lists_parameters(self) -> None:
        parser = build_arg_parser()
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("README 目录生成", text)
        for option in ("--repo", "--format", "--readme", "--output", "--max-files", "--debug"):
            self.assertIn(option, text)

    def test_debug_mode_and_default_mode_do_not_emit_stack(self) -> None:
        invalid = str(self.root / "missing")
        code_default, _, stderr_default = self._run(["--repo", invalid])
        code_debug, _, stderr_debug = self._run(["--repo", invalid, "--debug"])
        self.assertEqual(code_default, 2)
        self.assertEqual(code_debug, 2)
        self.assertNotIn("Traceback", stderr_default)
        self.assertNotIn("Traceback", stderr_debug)

    def test_stdout_contains_single_report_and_trailing_newline(self) -> None:
        self._matching_repo()
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue(stdout.endswith("\n"))
        self.assertEqual(stdout.count("RepoGuard README 目录生成报告"), 1)
        self.assertNotIn("调试信息", stdout)

    def test_json_format_contains_complete_fields(self) -> None:
        self._matching_repo()
        code, stdout, _ = self._run(["--repo", str(self.root), "--format", "json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        for key in (
            "format_version",
            "status",
            "scan_root",
            "document_count",
            "demo_project_count",
            "demo_project_suspected_count",
            "readme_found",
            "readme_path",
            "toc_block_found",
            "toc_marker_kind",
            "index",
            "index_markdown",
            "replacement_block",
            "diffs",
            "undetermined",
            "degraded",
            "warnings",
        ):
            self.assertIn(key, payload)

    def test_max_files_bounds(self) -> None:
        self._matching_repo()
        for value in ("29", "50001"):
            code, stdout, _ = self._run(["--repo", str(self.root), "--max-files", value])
            self.assertEqual(code, 2)
            self.assertIn("30～50000", stdout)
        code, _, _ = self._run(["--repo", str(self.root), "--max-files", "30"])
        self.assertEqual(code, 0)

    def test_no_network_socket_is_created(self) -> None:
        self._matching_repo()
        with patch("socket.socket", side_effect=AssertionError("network disabled")):
            code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("RepoGuard README 目录生成报告", stdout)


if __name__ == "__main__":
    unittest.main()
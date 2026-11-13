from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from app.health.cli import build_arg_parser, main, parse_health_options, validate_output_path


class HealthCliTests(unittest.TestCase):
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

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_argument_values(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--repo", str(self.root)])
        self.assertEqual(args.format, "text")
        self.assertEqual(args.zombie_days, 365)
        self.assertEqual(args.git, "auto")
        self.assertEqual(args.max_files, 5000)
        options, warnings = parse_health_options(args)
        self.assertEqual(options.zombie_days, 365)
        self.assertEqual(options.git_mode, "auto")
        self.assertEqual(options.max_files, 5000)
        self.assertEqual(warnings, ())

    def test_exit_code_zero_for_clean_repository(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root), "--git", "off"])
        self.assertEqual(code, 0)
        self.assertIn("仓库内未发现可巡检文件", stdout)

    def test_exit_code_one_for_high_risk(self) -> None:
        self._write("bad.py", "def hello():\n    return 1\n")
        code, stdout, _ = self._run(["--repo", str(self.root), "--git", "off"])
        self.assertEqual(code, 1)
        self.assertIn("高风险", stdout)

    def test_exit_code_two_for_invalid_root(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root / "missing")])
        self.assertEqual(code, 2)
        self.assertIn("输入存在错误", stdout)

    def test_max_files_bounds(self) -> None:
        for value in ("29", "50001"):
            code, stdout, _ = self._run(["--repo", str(self.root), "--max-files", value])
            self.assertEqual(code, 2)
            self.assertIn("30～50000", stdout)
        for value in ("30", "50000"):
            code, _, _ = self._run(["--repo", str(self.root), "--max-files", value, "--git", "off"])
            self.assertEqual(code, 0)

    def test_exit_code_three_for_degraded_repository(self) -> None:
        self._write("archive/old_notes.txt", "content")
        code, stdout, _ = self._run(["--repo", str(self.root)])
        self.assertEqual(code, 3)
        self.assertIn("降级", stdout)

    def test_json_format_contains_complete_fields(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root), "--format", "json", "--git", "off"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        for key in ("format_version", "status", "scan_root", "summary", "files", "zombie_candidates", "undetermined", "degraded", "warnings"):
            self.assertIn(key, payload)
        self.assertEqual(payload["summary"]["issue_count"], 0)

    def test_output_outside_repository_is_written(self) -> None:
        with TemporaryDirectory() as outside:
            target = Path(outside) / "health.json"
            code, stdout, _ = self._run(
                ["--repo", str(self.root), "--format", "json", "--output", str(target), "--git", "off"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["scan_root"], self.root.name)
            self.assertIn("format_version", stdout)

    def test_output_inside_repository_is_rejected(self) -> None:
        target = self.root / "health.json"
        code, stdout, _ = self._run(["--repo", str(self.root), "--output", str(target), "--git", "off"])
        self.assertEqual(code, 2)
        self.assertIn("仓库之外", stdout)
        self.assertFalse(target.exists())

    def test_output_existing_directory_returns_two(self) -> None:
        with TemporaryDirectory() as outside:
            code, stdout, _ = self._run(
                ["--repo", str(self.root), "--output", outside, "--git", "off"]
            )
            self.assertEqual(code, 2)
            self.assertIn("输入存在错误", stdout)
            self.assertIn("目录", stdout)

    def test_debug_mode_and_default_mode_do_not_emit_stack(self) -> None:
        invalid = str(self.root / "missing")
        code_default, _, stderr_default = self._run(["--repo", invalid])
        code_debug, _, stderr_debug = self._run(["--repo", invalid, "--debug"])
        self.assertEqual(code_default, 2)
        self.assertEqual(code_debug, 2)
        self.assertNotIn("Traceback", stderr_default)
        self.assertNotIn("Traceback", stderr_debug)

    def test_help_text_is_chinese_and_lists_parameters(self) -> None:
        parser = build_arg_parser()
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("全仓健康巡检", text)
        for option in ("--repo", "--format", "--output", "--zombie-days", "--git", "--max-files", "--config", "--debug"):
            self.assertIn(option, text)

    def test_invalid_zombie_days_falls_back_with_warning(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root), "--zombie-days", "0", "--git", "off"])
        self.assertNotEqual(code, 2)
        self.assertIn("30～3650", stdout)

    def test_invalid_git_choice_exits_two(self) -> None:
        parser = build_arg_parser()
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--git", "bad"])
        self.assertEqual(raised.exception.code, 2)

    def test_stdout_contains_single_report_and_trailing_newline(self) -> None:
        code, stdout, _ = self._run(["--repo", str(self.root), "--git", "off"])
        self.assertEqual(code, 0)
        self.assertTrue(stdout.endswith("\n"))
        self.assertEqual(stdout.count("RepoGuard 全仓健康巡检报告"), 1)
        self.assertNotIn("调试信息", stdout)


if __name__ == "__main__":
    unittest.main()
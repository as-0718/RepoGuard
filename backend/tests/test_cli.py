from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.core.rules import engine
from app.core.rules.common.models import DegradedModule, ExitCode, ReportStatus, build_report
from app.core.rules.common.report import report_to_json


def _run(args):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = engine.main(args)
    return code, stdout.getvalue(), stderr.getvalue()


def _write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _manifest(root: Path, text: str) -> Path:
    path = root / "changes.txt"
    path.write_text(text, encoding="utf-8")
    return path


class CliTest(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            self.assertEqual(_run(["--manifest", str(manifest), "--repo", str(root)])[0], int(ExitCode.OK))

            _write(root, "lab/bad.py", "def foo():\n    return 1\n")
            manifest = _manifest(root, "A lab/bad.py\n")
            self.assertEqual(_run(["--manifest", str(manifest), "--repo", str(root)])[0], int(ExitCode.MUST_FIX))

            self.assertEqual(_run(["--manifest", str(manifest), "--repo", str(root / "missing")])[0], int(ExitCode.INPUT_ERROR))

            degraded = build_report(
                status=ReportStatus.PARTIAL_DEGRADED,
                files=(),
                degraded_modules=(DegradedModule("代码检查", "执行异常，结果可能不完整"),),
            )
            with patch("app.core.rules.engine.run_check_file", return_value=degraded):
                self.assertEqual(_run(["--manifest", str(manifest), "--repo", str(root)])[0], int(ExitCode.EXECUTION_ERROR))

    def test_format_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            code, out, _ = _run(["--manifest", str(manifest), "--repo", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("RepoGuard 规则检查结果", out)

    def test_format_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            code, out, _ = _run(["--manifest", str(manifest), "--repo", str(root), "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("status", data)
        self.assertNotIn("\\u", out)

    def test_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            output = root / "report.json"
            code, _, _ = _run(["--manifest", str(manifest), "--repo", str(root), "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertTrue(output.exists())
            json.loads(output.read_text(encoding="utf-8"))

            before = sorted(item.name for item in root.iterdir())
            _run(["--manifest", str(manifest), "--repo", str(root)])
            after = sorted(item.name for item in root.iterdir())
        self.assertEqual(before, after)

    def test_stdin_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            with patch("sys.stdin", io.StringIO("A notes/ok.txt\n")):
                code, out, _ = _run(["--manifest", "-", "--repo", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("RepoGuard", out)

    def test_default_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            previous = os.getcwd()
            try:
                os.chdir(root)
                code, out, _ = _run(["--manifest", str(manifest)])
            finally:
                os.chdir(previous)
        self.assertEqual(code, 0)
        self.assertIn("RepoGuard", out)

    def test_config_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            config = root / "config.json"
            config.write_text("不是 JSON", encoding="utf-8")
            code, out, _ = _run(["--manifest", str(manifest), "--repo", str(root), "--config", str(config)])
        self.assertEqual(code, 0)
        self.assertIn("配置文件", out)

    def test_config_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/big.txt", "x" * 3000)
            manifest = _manifest(root, "A notes/big.txt\n")
            config = root / "config.json"
            config.write_text(
                json.dumps({"large_file_warn_mb": 0.001, "large_file_fail_mb": 0.002}),
                encoding="utf-8",
            )
            code, out, _ = _run(["--manifest", str(manifest), "--repo", str(root), "--config", str(config)])
        self.assertEqual(code, int(ExitCode.MUST_FIX))
        self.assertIn("sens-002", out)

    def test_debug_no_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = _manifest(root, "A notes/ok.txt\n")
            with patch("app.core.rules.engine.run_check_file", side_effect=RuntimeError("boom")):
                code, out, err = _run(["--manifest", str(manifest), "--repo", str(root), "--debug"])
        self.assertEqual(code, int(ExitCode.EXECUTION_ERROR))
        self.assertNotIn("ghp_abcdef123456", out + err)

    def test_no_stack_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            _, out, err = _run(["--manifest", str(manifest), "--repo", str(root)])
        self.assertNotIn("Traceback", out + err)

    def test_output_unwritable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/ok.txt", "hello\n")
            manifest = _manifest(root, "A notes/ok.txt\n")
            code, out, _ = _run([
                "--manifest", str(manifest), "--repo", str(root),
                "--output", str(root / "missing" / "report.json"),
            ])
        self.assertEqual(code, int(ExitCode.EXECUTION_ERROR))
        self.assertIn("无法写入输出文件", out)

    def test_help(self):
        with self.assertRaises(SystemExit) as context:
            engine.main(["--help"])
        self.assertEqual(context.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
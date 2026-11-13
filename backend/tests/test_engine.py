from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.rules import engine
from app.core.rules.common.models import (
    CheckReport,
    DegradedModule,
    ExitCode,
    IssueLevel,
    ReportStatus,
    build_report,
)
from app.core.rules.common.report import render_text, report_to_dict, report_to_json

BACKEND = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND / "app"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


class EngineTest(unittest.TestCase):
    def test_single_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            report = engine.run_check("A lab/example.py\n", root)
        rules = {finding.rule_id for group in report.files for finding in group.findings}
        self.assertIn("code-002", rules)

    def test_group_by_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/a.py", 'def foo():\n    return 1\n')
            _write(root, "notes/b.txt", "hello\n")
            report = engine.run_check("A lab/a.py\nA notes/b.txt\n", root)
        self.assertEqual(len(report.files), 2)
        self.assertEqual(len({group.file_path for group in report.files}), 2)

    def test_finding_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            report = engine.run_check("A lab/example.py\n", root)
        for group in report.files:
            for finding in group.findings:
                self.assertTrue(finding.file_path)
                self.assertIn(finding.level, (IssueLevel.MUST_FIX, IssueLevel.SUGGESTION))
                self.assertTrue(finding.message)
                self.assertTrue(finding.suggestion)
                self.assertRegex(finding.rule_id, r"^[a-z]+-\d{3}$")

    def test_report_contract(self):
        report = engine.run_check("", ".")
        data = report_to_dict(report)
        self.assertEqual(set(data.keys()), {"status", "summary", "files", "unparsed_lines", "degraded_modules", "warnings"})
        self.assertEqual(set(data["summary"].keys()), {
            "entry_count", "issue_count", "must_fix_count", "suggestion_count",
            "skipped_file_count", "degraded_module_count", "unparsed_line_count",
        })

    def test_summary_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            report = engine.run_check("A lab/example.py\n", root)
        summary = report.summary
        self.assertEqual(summary.issue_count, summary.must_fix_count + summary.suggestion_count)
        self.assertEqual(summary.must_fix_count, 1)
        self.assertEqual(summary.suggestion_count, 1)

    def test_sort_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/z.py", 'def foo():\n    return 1\n')
            _write(root, "lab/a.py", 'def foo():\n    return 1\n')
            report = engine.run_check("A lab/z.py\nA lab/a.py\n", root)
        self.assertEqual([group.file_path for group in report.files], ["lab/a.py", "lab/z.py"])
        for group in report.files:
            levels = [finding.level for finding in group.findings]
            if IssueLevel.MUST_FIX in levels and IssueLevel.SUGGESTION in levels:
                self.assertIs(levels[0], IssueLevel.MUST_FIX)

    def test_empty_report(self):
        report = engine.run_check("", ".")
        self.assertEqual(report.summary.entry_count, 0)
        self.assertEqual(report.files, ())
        self.assertTrue(any("变更清单为空" in item for item in report.warnings))

    def test_text_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            text = render_text(engine.run_check("A lab/example.py\n", root))
        self.assertIn("请先处理「必须修改」项", text)
        self.assertIn("必须修改", text)

    def test_json_utf8(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            text = report_to_json(engine.run_check("A lab/example.py\n", root))
        self.assertNotIn("\\u", text)
        json.loads(text)

    def test_empty_manifest_string(self):
        for text in ("", "   \n", "# 注释\n"):
            with self.subTest(text=text):
                report = engine.run_check(text, ".")
                self.assertEqual(report.summary.entry_count, 0)

    def test_input_error_repo_root(self):
        report = engine.run_check("A lab/a.py\n", "不存在的目录")
        self.assertIs(report.status, ReportStatus.INPUT_ERROR)
        self.assertEqual(report.summary.entry_count, 0)

    def test_manifest_unreadable(self):
        report = engine.run_check_file("不存在的清单.txt", ".")
        self.assertIs(report.status, ReportStatus.INPUT_ERROR)
        self.assertTrue(any("无法读取变更清单" in item for item in report.warnings))

    def test_degrade_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/a.txt", "hello\n")
            with patch("app.core.rules.engine.naming_check", side_effect=RuntimeError("boom")):
                report = engine.run_check("A lab/a.txt\n", root)
        self.assertIs(report.status, ReportStatus.PARTIAL_DEGRADED)
        self.assertTrue(report.degraded_modules)
        self.assertIn("结果可能不完整", render_text(report))

    def test_deleted_status_no_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("app.core.rules.engine.create_snapshot", side_effect=AssertionError("D 状态不应创建快照")):
                report = engine.run_check("D notes/old.md\n", root)
        self.assertEqual(report.files[0].findings, ())

    def test_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = _write(root, "lab/example.py", 'def foo():\n    return 1\n')

            def digest():
                stat = path.stat()
                return (path.read_bytes(), stat.st_size, stat.st_mtime_ns)

            before = digest()
            engine.run_check("M lab/example.py\n", root)
            after = digest()
        self.assertEqual(before, after)

    def test_no_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "docs/a.md", "[说明](https://example.com)\n")
            with patch("socket.socket", side_effect=AssertionError("不应发起网络请求")):
                report = engine.run_check("A docs/a.md\n", root)
        self.assertIsNotNone(report)

    def test_no_code_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/danger.py", '"""说明。"""\nraise RuntimeError("不应执行")\nopen("side_effect.txt", "w")\n')
            engine.run_check("A lab/danger.py\n", root)
            self.assertFalse((root / "side_effect.txt").exists())

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = engine.run_check("M ../outside.md\nM C:\\Windows\\win.ini\nM //server/share/a.md\n", root)
        self.assertEqual(len(report.files), 3)
        for group in report.files:
            self.assertIn("路径超出仓库范围", group.skip_reason or "")

    def test_encoding_compat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/bom.py", b"\xef\xbb\xbfdef foo():\n    return 1\n")
            _write(root, "lab/gb.py", "def foo():\n    # 中文注释\n    return 1\n".encode("gb18030"))
            _write(root, "lab/bad.py", b"\xff\xfe\x00\x01")
            report = engine.run_check("A lab/bom.py\nA lab/gb.py\nA lab/bad.py\n", root)
        groups = {group.file_path: group for group in report.files}
        self.assertIsNone(groups["lab/bom.py"].skip_reason)
        self.assertIsNone(groups["lab/gb.py"].skip_reason)
        self.assertIn("无法解码", groups["lab/bad.py"].skip_reason or "")

    def test_path_separator_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/uart/uart_demo.c", "int main(void) { return 0; }\n")
            report = engine.run_check("A lab\\uart\\uart_demo.c\n", root)
        self.assertEqual(report.files[0].file_path, "lab/uart/uart_demo.c")

    def test_report_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "lab/example.py", 'def foo():\n    return 1\n')
            first = report_to_json(engine.run_check("A lab/example.py\n", root))
            second = report_to_json(engine.run_check("A lab/example.py\n", root))
        self.assertEqual(first, second)

    def test_all_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = engine.run_check("A lab/missing1.txt\nA lab/missing2.txt\n", root)
        self.assertEqual(report.summary.issue_count, 0)
        self.assertTrue(any("本次未完成任何文件检查" in item for item in report.warnings))

    def test_partial_degraded_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "notes/a.txt", "hello\n")
            with patch("app.core.rules.engine.naming_check", side_effect=RuntimeError("boom")):
                report = engine.run_check("A notes/a.txt\n", root)
        self.assertIs(report.status, ReportStatus.PARTIAL_DEGRADED)
        self.assertEqual(engine.exit_code_for(report), ExitCode.EXECUTION_ERROR)

    def test_delivery_files_exist(self):
        rules_dir = APP_DIR / "core" / "rules"
        for name in ("naming.py", "code_scan.py", "link_check.py", "sensitive.py", "engine.py"):
            self.assertTrue((rules_dir / name).exists(), name)

    def test_requirements_txt(self):
        text = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
        engine_lines: list[str] = []
        web_lines: list[str] = []
        test_lines: list[str] = []
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                if "规则引擎" in stripped:
                    section = "engine"
                elif "Web API 运行依赖" in stripped:
                    section = "web"
                elif "仅 Web API 单元测试" in stripped:
                    section = "test"
                continue
            if not stripped:
                continue
            if section == "engine":
                engine_lines.append(stripped)
            elif section == "web":
                web_lines.append(stripped)
            elif section == "test":
                test_lines.append(stripped)
        self.assertEqual(engine_lines, [], "规则引擎段必须保持零第三方依赖")
        self.assertEqual(
            web_lines,
            ["fastapi==0.115.6", "uvicorn==0.34.0"],
            "Web API 运行依赖必须为固定版本 fastapi==0.115.6 与 uvicorn==0.34.0",
        )
        self.assertEqual(
            test_lines,
            ["httpx==0.28.1"],
            "Web API 单元测试依赖必须为固定版本 httpx==0.28.1",
        )
        self.assertTrue(
            all(marker in text for marker in ("规则引擎", "Web API 运行依赖", "仅 Web API 单元测试")),
            "requirements.txt 缺少引擎、Web 运行依赖或测试依赖分段标记",
        )
        for line in engine_lines + web_lines + test_lines:
            self.assertRegex(
                line,
                r"^[A-Za-z0-9_.-]+==\d+\.\d+\.\d+$",
                f"依赖必须使用精确版本，当前为：{line}",
            )
        for token in (">=", "~=", "latest"):
            for line in engine_lines + web_lines + test_lines:
                self.assertNotIn(token, line, f"依赖行不得使用非固定写法：{token}")

    def test_sample_manifest_covers_all_modules(self):
        manifest = Path(__file__).parent / "fixtures" / "sample_changes.txt"
        report = engine.run_check_file(manifest, REPO_ROOT / "demo-repo")
        prefixes = {finding.rule_id.split("-")[0] for group in report.files for finding in group.findings}
        self.assertTrue({"naming", "code", "link", "sens"}.issubset(prefixes), prefixes)

    def test_import_direction(self):
        allowed_absolute = {
            "__future__", "argparse", "ast", "collections", "dataclasses", "enum",
            "ipaddress", "json", "math", "os", "pathlib", "re", "sys", "time",
            "traceback", "types", "typing", "unittest",
        }
        allowed_api_absolute = allowed_absolute | set(__import__("sys").stdlib_module_names) | {"fastapi", "pydantic", "starlette", "app"}
        modules = {"engine", "naming", "code_scan", "link_check", "sensitive"}
        forbidden_api_exact = {
            "app.core.rules.common.file_io",
            "app.core.rules.common.manifest",
            "app.core.rules.common.config",
        }
        api_dir = APP_DIR / "api"

        def is_api_zone(path: Path) -> bool:
            return path.parent == api_dir or api_dir in path.parents

        for path in APP_DIR.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if is_api_zone(path):
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module]
                    for name in names:
                        root = name.split(".")[0]
                        self.assertIn(root, allowed_api_absolute, f"{path} 引入未授权依赖 {name}")
                        self.assertNotIn(name, forbidden_api_exact, f"{path} 不得导入引擎内部模块 {name}")
                        if name.startswith("app.core.rules."):
                            last = name.split(".")[-1]
                            self.assertNotIn(
                                last,
                                {"naming", "code_scan", "link_check", "sensitive"},
                                f"{path} 不得导入检查模块 {name}",
                            )
                        if path.name == "routes.py":
                            self.assertNotEqual(name, "app.api.app", f"{path} 不得反向导入 app.api.app")
                continue

            zone = "common" if "common" in path.parts else "rules"
            is_package_init = path.name == "__init__.py"
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        root = node.module.split(".")[0]
                        self.assertIn(root, allowed_absolute, f"{path} 引入第三方包 {node.module}")
                    elif node.level >= 1 and node.module and not is_package_init:
                        name = node.module.split(".")[0]
                        if zone == "common":
                            self.assertNotIn(name, modules, f"{path} 反向导入 {name}")
                        elif path.name == "engine.py":
                            self.assertNotIn(name, {"app", "rules"}, f"{path} 导入包根 {name}")
                        else:
                            self.assertNotIn(name, modules | {"engine"}, f"{path} 横向导入 {name}")

    @unittest.skipUnless(os.environ.get("RULES_PERF") == "1", "设置 RULES_PERF=1 后执行性能用例")
    def test_performance_500(self):
        import time

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(100):
                _write(root, f"lab/file_{index}.txt", "hello\n" * 20)
            manifest = "".join(f"A lab/file_{index}.txt\n" for index in range(100))
            manifest += "".join(f"A lab/missing_{index}.txt\n" for index in range(400))
            started = time.perf_counter()
            engine.run_check(manifest, root)
            self.assertLess(time.perf_counter() - started, 20.0)


if __name__ == "__main__":
    unittest.main()
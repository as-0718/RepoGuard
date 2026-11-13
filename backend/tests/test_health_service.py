from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core.rules.common.models import (
    ChangeStatus,
    DegradedModule,
    FileGroup,
    Finding,
    IssueLevel,
    ReportStatus,
    UnparsedLine,
    build_report,
)
from app.health.models import (
    DegradedItem,
    HealthFileEntry,
    HealthIssue,
    HealthOptions,
    HealthReport,
    HealthStatus,
    RiskLevel,
    ScanMeta,
    UndeterminedItem,
    ZombieCandidate,
    build_summary,
    validate_health_report,
)
from app.health.service import (
    exit_code_for,
    make_report,
    map_file_entries,
    run_health_check,
)
from app.health.cli import main as health_main, validate_output_path
from app.health.render import health_to_json, render_health_text
from app.readme.models import Confidence, DemoProject, DemoScanResult


def _snapshot(root: Path) -> dict[str, tuple[int, str, int]]:
    result: dict[str, tuple[int, str, int]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        result[path.relative_to(root).as_posix()] = (
            stat.st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.st_mtime_ns,
        )
    return result


def _write(root: Path, relative: str, content: str = "x") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class HealthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_run_check_is_called_exactly_once(self) -> None:
        _write(self.root, "a.md", "# A\n")
        fake = build_report(status=ReportStatus.OK, files=())
        with patch("app.health.service.run_check", return_value=fake) as mocked:
            run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(mocked.call_count, 1)

    def test_empty_repository_does_not_call_run_check(self) -> None:
        fake = build_report(status=ReportStatus.OK, files=())
        with patch("app.health.service.run_check", return_value=fake) as mocked:
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(report.meta.file_count, 0)
        self.assertEqual(report.summary.issue_count, 0)
        self.assertEqual(report.status, HealthStatus.OK)

    def test_counts_mapping_for_markdown_code_and_demos(self) -> None:
        _write(self.root, "README.md", "# 根\n")
        _write(self.root, "docs/a.md", "# A\n")
        _write(self.root, "docs/b.md", "# B\n")
        _write(self.root, "main.py", "print(1)\n")
        _write(self.root, "lib/x.c", "int x;\n")
        _write(self.root, "lib/y.h", "int y;\n")
        _write(self.root, "demoA/main.py", "print(1)\n")
        _write(self.root, "lab/uart/uart_demo.js", "console.log(1);\n")
        fake = build_report(status=ReportStatus.OK, files=())
        with patch("app.health.service.run_check", return_value=fake):
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(report.meta.file_count, 8)
        self.assertEqual(report.meta.markdown_count, 3)
        self.assertEqual(report.meta.code_file_count, 4)
        self.assertEqual(report.meta.demo_project_count, 1)
        self.assertEqual(report.meta.demo_project_suspected_count, 1)
        self.assertEqual(report.meta.scan_root, self.root.name)

    def test_risk_level_mapping_is_one_to_one(self) -> None:
        high = Finding(IssueLevel.MUST_FIX, "a.c", "公开函数缺少说明注释", "补充文档字符串", "code-002", line_no=2)
        suggestion = Finding(IssueLevel.SUGGESTION, "a.c", "建议项描述不少于八个字符", "按建议修改", "naming-001")
        report = build_report(
            status=ReportStatus.OK,
            files=(
                FileGroup("z.py", ChangeStatus.MODIFY, (Finding(IssueLevel.SUGGESTION, "z.py", "另一个建议描述八个字符", "修改", "code-007", line_no=5),)),
                FileGroup("a.c", ChangeStatus.MODIFY, (high, suggestion)),
            ),
        )
        entries = map_file_entries(report, None)
        self.assertEqual([item.file_path for item in entries], ["a.c", "z.py"])
        self.assertEqual(entries[0].risk_level, RiskLevel.HIGH)
        self.assertEqual(entries[1].risk_level, RiskLevel.SUGGESTION)
        self.assertEqual(entries[0].issue_count, 2)
        self.assertEqual(entries[0].findings[0].risk_level, RiskLevel.HIGH)
        self.assertEqual(entries[0].findings[1].line_no, None)
        self.assertEqual(entries[0].findings[0].source_module, "代码检查")
        self.assertEqual(entries[0].findings[1].source_module, "命名与目录检查")

    def test_summary_invariants_hold(self) -> None:
        high = HealthIssue("code-002", "代码检查", RiskLevel.HIGH, 3, "高风险描述八个字符", "修改", None)
        suggestion = HealthIssue("link-001", "链接检查", RiskLevel.SUGGESTION, None, "建议描述八个字符", "修改", None)
        files = (
            HealthFileEntry("a.py", RiskLevel.HIGH, 2, (high, suggestion)),
        )
        zombies = (ZombieCandidate("old.txt", "mtime", "2024-01-01", 400, 0, RiskLevel.SUGGESTION, "人工确认"),)
        undetermined = (UndeterminedItem("README.md", "入口文件不适用"),)
        degraded = (DegradedItem("Git", "仓库不是 Git 工作区"),)
        report = make_report(
            status=HealthStatus.OK,
            meta=ScanMeta(file_count=1),
            files=files,
            zombies=zombies,
            undetermined=undetermined,
            degraded=degraded,
            warnings=(),
            skipped_file_count=0,
        )
        self.assertEqual(validate_health_report(report), ())
        self.assertEqual(report.summary.issue_count, 2)
        self.assertEqual(report.summary.must_fix_count, 1)
        self.assertEqual(report.summary.suggestion_count, 1)
        self.assertEqual(report.summary.zombie_candidate_count, 1)
        self.assertEqual(report.summary.undetermined_count, 1)
        self.assertEqual(report.summary.degraded_count, 1)

    def test_degraded_modules_are_passed_through_verbatim(self) -> None:
        _write(self.root, "a.md", "# A\n")
        fake = build_report(
            status=ReportStatus.PARTIAL_DEGRADED,
            files=(),
            degraded_modules=(DegradedModule("代码检查", "模块执行异常，结果可能不完整"),),
        )
        with patch("app.health.service.run_check", return_value=fake):
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertTrue(any(item.item == "代码检查" and "模块执行异常" in item.reason for item in report.degraded))

    def test_skip_reasons_are_counted_and_capped(self) -> None:
        _write(self.root, "a.md", "# A\n")
        groups = tuple(
            FileGroup(f"f{index}.txt", ChangeStatus.MODIFY, (), "内容无法读取")
            for index in range(60)
        )
        fake = build_report(status=ReportStatus.PARTIAL_DEGRADED, files=groups)
        with patch("app.health.service.run_check", return_value=fake):
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(report.summary.skipped_file_count, 60)
        self.assertEqual(len(report.degraded), 51)
        self.assertTrue(any(item.item == "降级明细" and "10 条" in item.reason for item in report.degraded))

    def test_unparsed_lines_do_not_create_issues(self) -> None:
        _write(self.root, "a.md", "# A\n")
        fake = build_report(
            status=ReportStatus.PARTIAL_DEGRADED,
            files=(),
            unparsed_lines=(UnparsedLine(1, "bad line", "无法解析"),),
        )
        with patch("app.health.service.run_check", return_value=fake):
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(report.files, ())
        self.assertEqual(report.summary.issue_count, 0)
        self.assertEqual(validate_health_report(report), ())

    def test_inconsistent_report_is_downgraded(self) -> None:
        entry = HealthFileEntry("a.py", RiskLevel.HIGH, 99, ())
        report = make_report(
            status=HealthStatus.OK,
            meta=ScanMeta(),
            files=(entry,),
            zombies=(),
            undetermined=(),
            degraded=(),
            warnings=(),
            skipped_file_count=0,
        )
        self.assertEqual(report.status, HealthStatus.PARTIAL_DEGRADED)
        self.assertTrue(any(item.item == "报告" for item in report.degraded))
        self.assertIn("部分统计字段可能不一致", report.warnings)

    def test_read_only_snapshot_is_unchanged(self) -> None:
        _write(self.root, "docs/a.md", "# A\n")
        _write(self.root, "main.py", "print(1)\n")
        binary = self.root / "blob.bin"
        binary.write_bytes(b"\x00\x01\x02")
        before = _snapshot(self.root)
        run_health_check(self.root, HealthOptions(git_mode="off"))
        after = _snapshot(self.root)
        self.assertEqual(before, after)

    def test_no_network_socket_is_created(self) -> None:
        _write(self.root, "archive/old_notes.txt", "content")
        with patch("socket.socket", side_effect=AssertionError("network disabled")):
            report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertIsInstance(report, HealthReport)

    def test_output_inside_repository_is_rejected(self) -> None:
        _write(self.root, "a.md", "# A\n")
        target = self.root / "report.json"
        error = validate_output_path(self.root, target)
        self.assertIn("仓库之外", error or "")
        code = health_main(["--repo", str(self.root), "--output", str(target), "--git", "off"])
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())

    def test_binary_file_only_receives_volume_findings(self) -> None:
        media = self.root / "movie.mp4"
        with media.open("wb") as handle:
            handle.truncate(8 * 1024 * 1024)
        report = run_health_check(self.root, HealthOptions(git_mode="off"))
        self.assertEqual(report.meta.file_count, 1)
        self.assertGreaterEqual(report.summary.must_fix_count, 1)
        self.assertTrue(any(item.rule_id.startswith("sens-") for entry in report.files for item in entry.findings))

    def test_text_and_json_are_rendered_from_same_report(self) -> None:
        high = HealthIssue("code-002", "代码检查", RiskLevel.HIGH, 1, "高风险描述八个字符", "修改", None)
        files = (HealthFileEntry("a.py", RiskLevel.HIGH, 1, (high,)),)
        report = make_report(
            status=HealthStatus.OK,
            meta=ScanMeta(scan_root="demo-repo"),
            files=files,
            zombies=(),
            undetermined=(),
            degraded=(),
            warnings=(),
            skipped_file_count=0,
        )
        text = render_health_text(report)
        payload = json.loads(health_to_json(report))
        self.assertIn("RepoGuard 全仓健康巡检报告", text)
        self.assertEqual(payload["status"], "正常")
        self.assertEqual(payload["summary"]["must_fix_count"], 1)

    def test_input_error_for_tool_source_root(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        with patch("app.health.service.run_check") as mocked:
            report = run_health_check(project_root, HealthOptions(git_mode="off"))
        self.assertEqual(report.status, HealthStatus.INPUT_ERROR)
        self.assertEqual(exit_code_for(report), 2)
        self.assertEqual(mocked.call_count, 0)

    def test_max_files_exceeded_yields_partial_degraded(self) -> None:
        for index in range(31):
            _write(self.root, f"f{index:02d}.txt")
        fake = build_report(status=ReportStatus.OK, files=())
        with patch("app.health.service.run_check", return_value=fake) as mocked:
            report = run_health_check(self.root, HealthOptions(git_mode="off", max_files=30))
        self.assertEqual(report.meta.file_count, 30)
        self.assertEqual(report.status, HealthStatus.PARTIAL_DEGRADED)
        self.assertEqual(exit_code_for(report), 3)
        self.assertTrue(any("缩小巡检范围" in warning for warning in report.warnings))
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
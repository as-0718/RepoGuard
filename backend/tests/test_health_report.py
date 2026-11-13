from __future__ import annotations

import json
import unittest

from app.health.models import (
    DegradedItem,
    HealthFileEntry,
    HealthIssue,
    HealthReport,
    HealthStatus,
    HealthSummary,
    RiskLevel,
    ScanMeta,
    UndeterminedItem,
    ZombieCandidate,
    build_summary,
    sort_degraded,
    sort_files,
    sort_issues,
    sort_undetermined,
    sort_zombies,
)
from app.health.render import health_to_dict, health_to_json, render_health_text
from app.health.service import make_report


def _sample_report() -> HealthReport:
    high = HealthIssue("code-002", "代码检查", RiskLevel.HIGH, 10, "高风险问题描述八个字符", "修复高风险问题", "片段")
    suggestion = HealthIssue("naming-001", "命名与目录检查", RiskLevel.SUGGESTION, 5, "建议问题描述八个字符", "按建议修改", None)
    link = HealthIssue("link-001", "链接检查", RiskLevel.SUGGESTION, 3, "链接问题描述八个字符", "修正链接", None)
    files = (
        HealthFileEntry("b.md", RiskLevel.SUGGESTION, 1, (link,)),
        HealthFileEntry("a.py", RiskLevel.HIGH, 2, (high, suggestion)),
    )
    zombies = (ZombieCandidate("old.txt", "mtime", "2024-01-01", 500, 0, RiskLevel.SUGGESTION, "人工确认"),)
    undetermined = (UndeterminedItem("README.md", "入口或配置文件不适用僵尸判定"),)
    degraded = (DegradedItem("Git", "仓库不是 Git 工作区，已改用文件修改时间"),)
    summary = build_summary(
        files=sort_files(files),
        zombies=zombies,
        undetermined=undetermined,
        degraded=degraded,
        skipped_file_count=0,
    )
    meta = ScanMeta(
        scan_root="demo-repo",
        file_count=2,
        markdown_count=1,
        code_file_count=1,
        demo_project_count=0,
        demo_project_suspected_count=1,
        scanned_at="2026-01-01T00:00:00+00:00",
        duration_ms=10,
    )
    return HealthReport(
        status=HealthStatus.OK,
        meta=meta,
        summary=summary,
        files=tuple(sorted(files, key=lambda item: item.file_path)),
        zombie_candidates=zombies,
        undetermined=undetermined,
        degraded=degraded,
        warnings=("测试警告",),
    )


def _empty_report() -> HealthReport:
    return HealthReport(
        status=HealthStatus.OK,
        meta=ScanMeta(),
        summary=HealthSummary(0, 0, 0, 0, 0, 0, 0),
    )


class HealthReportTests(unittest.TestCase):
    def test_text_output_order(self) -> None:
        text = render_health_text(_sample_report())
        markers = ["【高风险】", "【建议】", "【僵尸候选】", "【无法判定】", "【降级项】", "【警告】"]
        positions = [text.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("请先处理高风险项", text)

    def test_empty_sections_have_explicit_messages(self) -> None:
        text = render_health_text(_empty_report())
        self.assertIn("未发现高风险问题。", text)
        self.assertIn("未发现建议项。", text)
        self.assertIn("未发现僵尸候选。", text)
        self.assertIn("无无法判定项。", text)
        self.assertIn("本次巡检未发生降级。", text)
        self.assertNotIn("【警告】", text)

    def test_input_error_text_only_contains_reason(self) -> None:
        report = HealthReport(
            status=HealthStatus.INPUT_ERROR,
            meta=ScanMeta(),
            summary=HealthSummary(0, 0, 0, 0, 0, 0, 0),
            warnings=("仓库根目录不存在",),
        )
        self.assertEqual(render_health_text(report), "输入存在错误，本次巡检未执行：仓库根目录不存在")

    def test_json_contains_unescaped_chinese(self) -> None:
        raw = health_to_json(_sample_report())
        self.assertNotIn("\\u", raw)
        payload = json.loads(raw)
        self.assertEqual(payload["files"][0]["findings"][0]["message"], "高风险问题描述八个字符")

    def test_json_top_level_key_order(self) -> None:
        payload = health_to_dict(_sample_report())
        self.assertEqual(
            list(payload.keys()),
            [
                "format_version",
                "status",
                "scan_root",
                "file_count",
                "markdown_count",
                "code_file_count",
                "demo_project_count",
                "demo_project_suspected_count",
                "summary",
                "files",
                "zombie_candidates",
                "undetermined",
                "degraded",
                "warnings",
                "scanned_at",
                "duration_ms",
            ],
        )

    def test_stable_sorting_rules(self) -> None:
        high_late = HealthIssue("code-002", "代码检查", RiskLevel.HIGH, 20, "高风险较晚行描述", "修改", None)
        high_early = HealthIssue("code-001", "代码检查", RiskLevel.HIGH, 2, "高风险较早行描述", "修改", None)
        suggestion = HealthIssue("link-001", "链接检查", RiskLevel.SUGGESTION, 1, "建议问题描述八个字符", "修改", None)
        ordered = sort_issues([suggestion, high_late, high_early])
        self.assertEqual([item.line_no for item in ordered], [2, 20, 1])

        self.assertEqual([item.file_path for item in sort_files([HealthFileEntry("b", RiskLevel.HIGH, 0), HealthFileEntry("a", RiskLevel.HIGH, 0)])], ["a", "b"])
        self.assertEqual([item.file_path for item in sort_zombies([ZombieCandidate("b", "mtime", "2024-01-01", 1, 0, RiskLevel.SUGGESTION, "x"), ZombieCandidate("a", "mtime", "2024-01-01", 1, 0, RiskLevel.SUGGESTION, "x")])], ["a", "b"])
        self.assertEqual([item.item for item in sort_undetermined([UndeterminedItem("b", "r"), UndeterminedItem("a", "r")])], ["a", "b"])
        degraded = sort_degraded([DegradedItem("报告", "r1"), DegradedItem("遍历", "r2"), DegradedItem("Git", "r3")])
        self.assertEqual([item.item for item in degraded], ["遍历", "Git", "报告"])

    def test_deterministic_excluding_time_fields(self) -> None:
        first = _sample_report()
        second = _sample_report()
        first_dict = health_to_dict(first)
        second_dict = health_to_dict(second)
        for key in ("scanned_at", "duration_ms"):
            first_dict.pop(key)
            second_dict.pop(key)
        self.assertEqual(first_dict, second_dict)

    def test_empty_result_has_complete_structure(self) -> None:
        payload = health_to_dict(_empty_report())
        self.assertEqual(payload["summary"]["issue_count"], 0)
        self.assertEqual(payload["files"], [])
        self.assertEqual(payload["zombie_candidates"], [])
        self.assertEqual(payload["undetermined"], [])
        self.assertEqual(payload["degraded"], [])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["scan_root"], "<repo>")

    def test_undetermined_is_not_counted_as_issue(self) -> None:
        report = _sample_report()
        self.assertEqual(report.summary.issue_count, 3)
        self.assertEqual(report.summary.undetermined_count, 1)

    def test_inconsistent_summary_downgrades_report(self) -> None:
        entry = HealthFileEntry("a.py", RiskLevel.HIGH, 7, ())
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

    def test_no_absolute_path_in_output(self) -> None:
        text = render_health_text(_sample_report())
        raw = health_to_json(_sample_report())
        for value in (text, raw):
            self.assertNotIn("C:\\", value)
            self.assertNotIn("Users", value)
            self.assertNotIn("\\\\", value)

    def test_degraded_items_are_sorted_and_deduplicated(self) -> None:
        items = [
            DegradedItem("报告", "r1"),
            DegradedItem("遍历", "r2"),
            DegradedItem("遍历", "r2"),
            DegradedItem("Git", "r3"),
        ]
        ordered = sort_degraded(items)
        self.assertEqual([(item.item, item.reason) for item in ordered], [("遍历", "r2"), ("Git", "r3"), ("报告", "r1")])

    def test_over_limit_and_empty_repository_warnings(self) -> None:
        over_limit = HealthReport(
            status=HealthStatus.PARTIAL_DEGRADED,
            meta=ScanMeta(file_count=5001),
            summary=HealthSummary(0, 0, 0, 0, 0, 0, 1),
            degraded=(DegradedItem("遍历", "文件数超过上限 5000"),),
            warnings=("文件数超过巡检上限，请缩小巡检范围后重试",),
        )
        text = render_health_text(over_limit)
        self.assertIn("超过上限", text)
        self.assertIn("请缩小巡检范围后重试", text)

        empty_text = render_health_text(
            HealthReport(
                status=HealthStatus.OK,
                meta=ScanMeta(),
                summary=HealthSummary(0, 0, 0, 0, 0, 0, 0),
                warnings=("仓库内未发现可巡检文件",),
            )
        )
        self.assertIn("仓库内未发现可巡检文件", empty_text)


if __name__ == "__main__":
    unittest.main()
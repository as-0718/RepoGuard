from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
from app.integrations.mock import MockOpenApiAdapter
from app.integrations.models import OpenApiMode
from app.webhook.models import ChangedFilesSource, EventKind, NormalizedEvent, ReviewJob, utc_now
from app.webhook.render import apply_marker, redact_comment, render_comment, render_groups, truncate_comment
from app.webhook.service import WebhookService
from app.webhook.settings import WebhookConfig
from tests.webhook_helpers import WebhookASGIClient  # noqa: F401  (kept out of the network path)


def _event(event_id: str = "evt-comment") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        event_kind=EventKind.CREATED,
        repository_identifier="acme/lab-01",
        repo_label="lab-01",
        pull_request_number=12,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=("a.py", "b.py"),
        changed_files_source=ChangedFilesSource.PAYLOAD,
        changed_files_available=True,
        illegal_paths=(),
        signature_verified=True,
        occurred_at=utc_now(),
    )


def _finding(level: IssueLevel, path: str, message: str, suggestion: str, rule_id: str, line_no: int = 1) -> Finding:
    return Finding(level=level, file_path=path, message=message, suggestion=suggestion, rule_id=rule_id, line_no=line_no)


def _config(**overrides) -> WebhookConfig:
    values = {
        "secret": "fake",
        "max_comment_chars": 60_000,
        "openapi_mode": OpenApiMode.DISABLED,
        "notify_on_clean": True,
    }
    values.update(overrides)
    return WebhookConfig(**values)


class CommentTest(unittest.TestCase):
    def test_comment_structure(self):
        must = _finding(IssueLevel.MUST_FIX, "a.py", "发现高风险写法需要立即修正", "请按照规范重写该逻辑", "naming-001")
        tip = _finding(IssueLevel.SUGGESTION, "a.py", "建议优化变量命名可读性", "使用更具描述性的名称", "naming-002")
        tip2 = _finding(IssueLevel.SUGGESTION, "b.py", "建议补充文档说明使用方式", "在模块顶部补充说明", "link-001", 3)
        report = build_report(
            status=ReportStatus.PARTIAL_DEGRADED,
            files=(
                FileGroup("a.py", ChangeStatus.MODIFY, findings=(must, tip)),
                FileGroup("b.py", ChangeStatus.MODIFY, findings=(tip2,), skip_reason="文件无法读取"),
            ),
            unparsed_lines=(UnparsedLine(1, "???", "格式不合法"),),
            degraded_modules=(DegradedModule("命名与目录检查", "模块降级说明"),),
        )
        payload = render_comment(report, _event(), _config())
        markdown = payload.markdown
        self.assertLess(markdown.index("【必须修改】"), markdown.index("【优化建议】"))
        self.assertLess(markdown.index(must.message), markdown.index(tip.message))
        summary = report.summary
        self.assertIn(f"问题统计：共 {summary.issue_count} 个（必须修改 {summary.must_fix_count}，优化建议 {summary.suggestion_count}）", markdown)
        self.assertIn(f"变更文件：{len(_event().changed_files)} 个（来源：payload）", markdown)
        self.assertIn(f"降级模块：{summary.degraded_module_count} 个", markdown)
        self.assertIn(f"未完成检查文件：{summary.skipped_file_count} 个", markdown)
        self.assertIn(f"无法解析行：{summary.unparsed_line_count} 条", markdown)
        self.assertEqual(payload.must_fix_count, summary.must_fix_count)
        self.assertEqual(payload.suggestion_count, summary.suggestion_count)
        self.assertEqual(payload.issue_count, summary.issue_count)
        self.assertEqual(payload.skipped_file_count, summary.skipped_file_count)
        self.assertEqual(payload.degraded_module_count, summary.degraded_module_count)
        groups = render_groups(report)
        self.assertEqual(groups[0], (must,))
        self.assertEqual(groups[1], (tip, tip2))
        self.assertEqual(markdown.count("规则标识："), 3)

    def test_comment_truncation(self):
        files = []
        for index in range(15):
            findings = (
                _finding(
                    IssueLevel.MUST_FIX,
                    f"a{index}.py",
                    f"必须修改的问题描述编号 {index:02d} 需要立即处理",
                    f"请按照规范第 {index:02d} 条重写",
                    f"must-{index:02d}",
                ),
                _finding(
                    IssueLevel.SUGGESTION,
                    f"b{index}.py",
                    f"优化建议问题描述编号 {index:02d} 可以延后处理",
                    f"建议采用第 {index:02d} 种优化方式",
                    f"tip-{index:02d}",
                ),
            )
            files.append(FileGroup(f"file{index}.py", ChangeStatus.MODIFY, findings=findings))
        report = build_report(status=ReportStatus.OK, files=tuple(files))
        limit = 1_500
        config = _config(max_comment_chars=limit)
        payload = render_comment(report, _event(), config)
        markdown = payload.markdown
        self.assertLessEqual(len(markdown), limit)
        self.assertTrue(markdown.endswith(payload.marker))
        self.assertTrue(payload.truncated)
        displayed = markdown.count("规则标识：")
        total = report.summary.must_fix_count + report.summary.suggestion_count
        self.assertEqual(displayed, markdown.count("- 第 "))
        self.assertEqual(payload.omitted_must_fix + payload.omitted_suggestions, total - displayed)
        self.assertGreater(payload.omitted_must_fix + payload.omitted_suggestions, 0)
        self.assertGreaterEqual(payload.omitted_must_fix, 0)
        self.assertGreaterEqual(payload.omitted_suggestions, 0)
        body_without_marker = markdown[: -len(payload.marker)].rstrip()
        last_line = body_without_marker.splitlines()[-1]
        self.assertTrue(last_line.endswith("）"), last_line)

    def test_comment_marker(self):
        marker = "<!-- repoguard:event:evt-marker -->"
        self.assertEqual(apply_marker("正文", marker), "正文\n\n" + marker)
        report = build_report(status=ReportStatus.OK, files=(FileGroup("a.py", ChangeStatus.MODIFY),))
        payload = render_comment(report, _event("evt-marker"), _config())
        self.assertEqual(payload.marker, marker)
        self.assertEqual(payload.markdown.count(marker), 1)
        self.assertTrue(payload.markdown.endswith(marker))
        truncated, omitted_must, omitted_tip, flag = truncate_comment("abc", len(marker) + 10, marker)
        self.assertTrue(truncated.endswith(marker))
        self.assertEqual((omitted_must, omitted_tip, flag), (0, 0, False))
        with self.assertRaises(Exception):
            truncate_comment("abc", len(marker), marker)

    def test_comment_redaction(self):
        text = "令牌 token-abc123 位于 C:\\workspace\\repo\\a.py 与 /home/alice/secret.txt"
        output = redact_comment(text, secrets=("token-abc123",), absolute_roots=("C:\\workspace\\repo",))
        self.assertNotIn("token-abc123", output)
        self.assertIn("****", output)
        self.assertNotIn("C:\\workspace\\repo", output)
        self.assertNotIn("/home/alice", output)
        self.assertNotIn("token-****", output)
        for secret in ("", "abc"):
            self.assertEqual(redact_comment(secret, secrets=(secret,)), secret)

    def test_comment_empty_vs_not_executed(self):
        clean = build_report(status=ReportStatus.OK, files=(FileGroup("a.py", ChangeStatus.MODIFY),))
        event = _event()
        executed = render_comment(clean, event, _config())
        self.assertIn("本次检查未发现问题", executed.markdown)
        self.assertEqual(executed.issue_count, 0)
        self.assertEqual(executed.check_status, "正常")

        not_executed = render_comment(None, event, _config(), executed=False)
        self.assertNotIn("本次检查未发现问题", not_executed.markdown)
        self.assertIn("本次未执行检查", not_executed.markdown)
        self.assertEqual(not_executed.check_status, "未执行")

        timeout = render_comment(None, event, _config(), executed=False, status_reason="检查超时")
        self.assertNotIn("本次检查未发现问题", timeout.markdown)
        self.assertIn("检查超时：本次未完成检查", timeout.markdown)
        self.assertEqual(timeout.check_status, "超时")

        failed = render_comment(None, event, _config(), executed=False, status_reason="检查失败")
        self.assertNotIn("本次检查未发现问题", failed.markdown)
        self.assertIn("检查未能完成：本次未完成检查", failed.markdown)
        self.assertEqual(failed.check_status, "失败")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "lab-01"
            root.mkdir(parents=True, exist_ok=True)
            config = _config(openapi_mode=OpenApiMode.MOCK, notify_on_clean=False)
            adapter = MockOpenApiAdapter()
            service = WebhookService(config, _web_settings(root), runner=lambda *args: clean, adapter=adapter)
            job = ReviewJob(
                event=event,
                repo_root=root.resolve(),
                manifest_text="M a.py\n",
                entry_count=1,
                created_at=utc_now(),
                attempt=1,
                request_id="req-clean",
            )
            record = service.process_job(job)
            self.assertEqual(record.delivery_status, "skipped")
            self.assertEqual(record.reason, "无问题且配置为不回报")
            self.assertEqual(adapter.comments, ())


def _web_settings(root: Path):
    from app.api.settings import WebSettings

    return WebSettings(allowed_repo_roots=(root.resolve(),), default_repo=root.name, static_dir=root)


if __name__ == "__main__":
    unittest.main()
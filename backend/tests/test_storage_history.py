from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.storage import (
    count_snapshots,
    db_available,
    get_snapshot_with_issues,
    init_db,
    list_fix_events,
    list_snapshots,
    record_fix_event,
    record_snapshot,
)


def _issue(
    file_path: str,
    line_no: int | None,
    rule_id: str,
    source_module: str,
    risk_level: str,
    message: str,
    suggestion: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        file_path=file_path,
        line_no=line_no,
        rule_id=rule_id,
        source_module=source_module,
        risk_level=risk_level,
        message=message,
        suggestion=suggestion,
    )


class StorageHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="repoguard-storage-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.db_path = Path(self.temp_dir) / "data" / "repoguard.db"
        init_db(self.db_path)

    def _record(self, repo_label: str, repo_key: str, scanned_at: str, issues: tuple[object, ...]):
        return record_snapshot(
            self.db_path,
            repo_label=repo_label,
            repo_key=repo_key,
            scanned_at=scanned_at,
            duration_ms=12,
            files_count=3,
            issue_count=len(issues),
            must_fix_count=1,
            suggestion_count=1,
            zombie_count=0,
            undetermined_count=2,
            status="ok",
            issues=issues,
        )

    def test_init_db_is_idempotent(self) -> None:
        # 重复建表不应报错
        init_db(self.db_path)
        self.assertTrue(self.db_path.is_file())

    def test_record_and_detail_roundtrip(self) -> None:
        issues = (
            _issue("src/a.py", 10, "code-001", "代码检查", "高风险", "未处理异常", "补充异常捕获"),
            _issue("docs/b.md", None, "link-002", "链接检查", "建议", "链接缺失标题", "补充链接文本"),
        )
        snapshot_id = self._record("demo-repo", "key-a", "2026-01-01T00:00:00+00:00", issues)
        self.assertIsNotNone(snapshot_id)

        detail = get_snapshot_with_issues(self.db_path, snapshot_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["repo_label"], "demo-repo")
        self.assertEqual(detail["repo_key"], "key-a")
        self.assertEqual(detail["issue_count"], 2)
        self.assertEqual(detail["must_fix_count"], 1)
        self.assertEqual(detail["undetermined_count"], 2)
        self.assertEqual(len(detail["issues"]), 2)

        first = detail["issues"][0]
        self.assertEqual(first["file_path"], "src/a.py")
        self.assertEqual(first["line_no"], 10)
        self.assertEqual(first["rule_id"], "code-001")
        self.assertEqual(first["risk_level"], "高风险")
        self.assertEqual(first["suggestion"], "补充异常捕获")

    def test_list_snapshots_order_and_filter(self) -> None:
        first = self._record("repo-a", "key-a", "2026-01-01T00:00:00+00:00", ())
        second = self._record("repo-a", "key-a", "2026-01-02T00:00:00+00:00", ())
        third = self._record("repo-b", "key-b", "2026-01-03T00:00:00+00:00", ())

        all_records = list_snapshots(self.db_path)
        self.assertEqual([item["id"] for item in all_records], [third, second, first])

        filtered = list_snapshots(self.db_path, repo_key="key-a")
        self.assertEqual([item["id"] for item in filtered], [second, first])

        limited = list_snapshots(self.db_path, limit=1)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0]["id"], third)

    def test_count_snapshots_total_and_filtered(self) -> None:
        self._record("repo-a", "key-a", "2026-01-01T00:00:00+00:00", ())
        self._record("repo-a", "key-a", "2026-01-02T00:00:00+00:00", ())
        self._record("repo-b", "key-b", "2026-01-03T00:00:00+00:00", ())

        self.assertEqual(count_snapshots(self.db_path), 3)
        self.assertEqual(count_snapshots(self.db_path, repo_key="key-a"), 2)
        self.assertEqual(count_snapshots(self.db_path, repo_key="key-b"), 1)
        self.assertEqual(count_snapshots(self.db_path, repo_key="no-such-key"), 0)

    def test_detail_missing_returns_none(self) -> None:
        self.assertIsNone(get_snapshot_with_issues(self.db_path, 99999))

    def test_db_available(self) -> None:
        self.assertTrue(db_available(self.db_path))

    def test_fix_event_roundtrip_and_filter(self) -> None:
        first = record_fix_event(
            self.db_path,
            repo_label="repo-a",
            action="apply",
            result="success",
            applied_count=2,
            skipped_count=0,
            files=["docs/a.md", "docs/b.md"],
            duration_ms=31,
            request_id="req-1",
        )
        second = record_fix_event(
            self.db_path,
            repo_label="repo-a",
            action="rollback",
            result="partial",
            restored_count=1,
            failed_count=1,
            files=["docs/a.md"],
            duration_ms=12,
            request_id="req-2",
        )
        third = record_fix_event(
            self.db_path,
            repo_label="repo-b",
            action="apply",
            result="failed",
            skipped_count=1,
            files=[],
            duration_ms=5,
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)

        all_events = list_fix_events(self.db_path)
        self.assertEqual([item["id"] for item in all_events], [third, second, first])
        self.assertEqual(all_events[0]["action"], "apply")
        self.assertEqual(all_events[0]["result"], "failed")

        filtered = list_fix_events(self.db_path, repo_label="repo-a")
        self.assertEqual([item["id"] for item in filtered], [second, first])
        self.assertEqual(filtered[0]["files"], ["docs/a.md"])
        self.assertEqual(filtered[1]["files"], ["docs/a.md", "docs/b.md"])

        limited = list_fix_events(self.db_path, limit=1)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0]["id"], third)

    def test_fix_event_file_entries_with_mtime(self) -> None:
        record_fix_event(
            self.db_path,
            repo_label="repo-a",
            action="apply",
            result="success",
            applied_count=1,
            files=[{"path": "docs/a.md", "mtime": "2026-01-01T10:00:00+00:00"}],
            duration_ms=9,
            request_id="req-m",
        )
        events = list_fix_events(self.db_path, repo_label="repo-a")
        self.assertEqual(len(events), 1)
        entry = events[0]["files"][0]
        self.assertEqual(entry["path"], "docs/a.md")
        self.assertEqual(entry["mtime"], "2026-01-01T10:00:00+00:00")

    def test_fix_event_degradation_on_unwritable_path(self) -> None:
        blocker = Path(self.temp_dir) / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        bad_path = blocker / "nested" / "repoguard.db"

        self.assertIsNone(
            record_fix_event(
                bad_path,
                repo_label="x",
                action="apply",
                result="failed",
                files=[],
            )
        )
        self.assertEqual(list_fix_events(bad_path), [])

    def test_degradation_on_unwritable_path(self) -> None:
        blocker = Path(self.temp_dir) / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        bad_path = blocker / "nested" / "repoguard.db"

        self.assertIsNone(
            record_snapshot(
                bad_path,
                repo_label="x",
                repo_key="k",
                scanned_at="2026-01-01T00:00:00+00:00",
                duration_ms=1,
                files_count=0,
                issue_count=0,
                must_fix_count=0,
                suggestion_count=0,
                zombie_count=0,
                undetermined_count=0,
                status="ok",
                issues=(),
            )
        )
        self.assertEqual(list_snapshots(bad_path), [])
        self.assertIsNone(get_snapshot_with_issues(bad_path, 1))
        self.assertFalse(db_available(bad_path))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import datetime
import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app.health.models import DegradedItem, HealthOptions, RiskLevel, UndeterminedItem, resolve_options
from app.health.zombie import (
    GitActivity,
    GitBudget,
    collect_reference_counts,
    detect_zombies,
    evaluate_mtime_credibility,
    get_git_last_commit,
    is_generic_basename,
    zombie_exemption_reason,
)
from app.shared.repo_walk import WalkedFile


NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
NOW_TS = NOW.timestamp()
DAY = 86400.0


def _chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


class HealthZombieTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _file(self, relative: str, mtime: float) -> WalkedFile:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
        return WalkedFile(relative, path, path.stat().st_size, mtime, path.suffix)

    def _spread_files(self, target: WalkedFile) -> list[WalkedFile]:
        return [
            target,
            self._file("archive/second_notes.txt", NOW_TS - 300 * DAY),
            self._file("archive/third_notes.txt", NOW_TS - 200 * DAY),
            self._file("archive/fourth_notes.txt", NOW_TS - 100 * DAY),
            self._file("archive/recent_notes.txt", NOW_TS - 10 * DAY),
        ]

    def test_git_basis_candidate(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        old_ts = NOW_TS - 500 * DAY
        with patch("app.health.zombie.is_git_work_tree", return_value=True), patch(
            "app.health.zombie.get_git_last_commit",
            return_value=GitActivity(True, old_ts, None),
        ):
            result = detect_zombies(self.root, files, HealthOptions(now=NOW, git_mode="auto"), text_reader=lambda item: "")
        candidate = next((item for item in result.candidates if item.file_path == target.path), None)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.basis, "git")
        self.assertGreaterEqual(candidate.idle_days, 365)

    def test_mtime_basis_candidate(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        candidate = next((item for item in result.candidates if item.file_path == target.path), None)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.basis, "mtime")

    def test_threshold_is_configurable(self) -> None:
        target = self._file("archive/legacy_module.py", NOW_TS - 100 * DAY)
        files = self._spread_files(target)
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off", zombie_days=90),
            text_reader=lambda item: "",
        )
        candidate = next((item for item in result.candidates if item.file_path == target.path), None)
        self.assertIsNotNone(candidate)
        self.assertGreaterEqual(candidate.idle_days, 90)

    def test_invalid_threshold_falls_back_with_warning(self) -> None:
        for value in (0, 20, 4000):
            options, warnings = resolve_options(HealthOptions(zombie_days=value))
            self.assertEqual(options.zombie_days, 365)
            self.assertTrue(any("30～3650" in warning for warning in warnings))

    def test_referenced_file_is_not_a_candidate(self) -> None:
        target = self._file("archive/target.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        refs = self._file("docs/refs.md", NOW_TS - 5 * DAY)
        files.append(refs)

        def reader(item: WalkedFile) -> str:
            if item.path == refs.path:
                return "详见 archive/target.txt"
            return ""

        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=reader,
        )
        self.assertFalse(any(item.file_path == target.path for item in result.candidates))
        self.assertFalse(any(item.item == target.path for item in result.undetermined))

    def test_git_unavailable_is_degraded(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="auto"),
            text_reader=lambda item: "",
        )
        self.assertTrue(any(item.item == "Git" and "不是 Git 工作区" in item.reason for item in result.degraded))

    def test_git_timeout_is_degraded(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        with patch("app.health.zombie.is_git_work_tree", return_value=True), patch(
            "app.health.zombie.get_git_last_commit",
            return_value=GitActivity(False, None, "Git 最近提交时间查询超时"),
        ):
            result = detect_zombies(
                self.root,
                files,
                HealthOptions(now=NOW, git_mode="auto"),
                text_reader=lambda item: "",
            )
        self.assertTrue(any("超时" in item.reason for item in result.degraded))

    def test_git_budget_exhaustion_skips_subprocess(self) -> None:
        budget = GitBudget(time.monotonic() - 1.0)
        with patch("app.health.zombie.subprocess.run") as mocked:
            activity = get_git_last_commit(self.root, "a.txt", budget=budget)
        self.assertFalse(activity.available)
        self.assertIn("预算", activity.reason or "")
        self.assertEqual(mocked.call_count, 0)

    def test_mtime_batch_checkout_is_untrusted(self) -> None:
        files = [self._file(f"archive/item{index}.txt", NOW_TS - DAY) for index in range(5)]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertFalse(result.mtime_credible)
        self.assertTrue(result.undetermined)
        self.assertTrue(all("批量检出" in item.reason for item in result.undetermined))

    def test_reference_scan_incomplete_is_undetermined(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        broken = self._file("docs/broken.md", NOW_TS - 5 * DAY)
        files.append(broken)

        def reader(item: WalkedFile) -> str | None:
            if item.path == broken.path:
                return None
            return ""

        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=reader,
        )
        self.assertFalse(result.reference_complete)
        self.assertTrue(result.undetermined)
        self.assertTrue(all("引用统计不完整" in item.reason for item in result.undetermined))
        self.assertTrue(any("1 个文本文件" in item.reason for item in result.undetermined))

    def test_generic_basename_is_undetermined(self) -> None:
        files = [
            self._file("README.md", NOW_TS - 400 * DAY),
            self._file("requirements.txt", NOW_TS - 400 * DAY),
        ]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(result.candidates, ())
        self.assertEqual({item.item for item in result.undetermined}, {"README.md", "requirements.txt"})
        self.assertTrue(all("入口或配置文件" in item.reason for item in result.undetermined))

    def test_demo_path_is_exempt(self) -> None:
        files = [self._file("lab/uart/uart_demo.c", NOW_TS - 400 * DAY)]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(result.candidates, ())
        self.assertTrue(any("示例文件" in item.reason for item in result.undetermined))

    def test_entry_and_build_files_are_exempt(self) -> None:
        files = [
            self._file("main.py", NOW_TS - 400 * DAY),
            self._file("CMakeLists.txt", NOW_TS - 400 * DAY),
        ]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(result.candidates, ())
        self.assertEqual(len(result.undetermined), 2)
        self.assertTrue(all("入口或配置文件" in item.reason for item in result.undetermined))

    def test_config_files_are_exempt(self) -> None:
        files = [
            self._file(".env", NOW_TS - 400 * DAY),
            self._file(".gitignore", NOW_TS - 400 * DAY),
        ]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(result.candidates, ())
        reasons = {item.item: item.reason for item in result.undetermined}
        self.assertIn("配置文件", reasons[".env"])
        self.assertIn("入口或配置文件", reasons[".gitignore"])

    def test_weak_binary_signal_is_not_candidate(self) -> None:
        files = [self._file("archive/blob.bin", NOW_TS - 400 * DAY)]
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(result.candidates, ())
        self.assertFalse(any(item.item == "archive/blob.bin" for item in result.undetermined))

    def test_undetermined_reasons_are_chinese_and_candidate_is_suggestion(self) -> None:
        target = self._file("archive/old_notes.txt", NOW_TS - 400 * DAY)
        files = self._spread_files(target)
        files.append(self._file("README.md", NOW_TS - 400 * DAY))
        result = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertTrue(result.undetermined)
        self.assertTrue(all(item.reason and _chinese(item.reason) for item in result.undetermined))
        candidate = next(item for item in result.candidates if item.file_path == target.path)
        self.assertEqual(candidate.risk_level, RiskLevel.SUGGESTION)
        self.assertEqual(candidate.reference_count, 0)

    def test_git_command_uses_read_only_argument_list(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=b"1700000000\n")
        with patch("app.health.zombie.subprocess.run", return_value=completed) as mocked:
            activity = get_git_last_commit(self.root, "a.txt")
        self.assertTrue(activity.available)
        self.assertEqual(activity.timestamp, 1700000000.0)
        command = mocked.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[0], "git")
        self.assertIn("log", command)
        self.assertIn("--format=%ct", command)
        self.assertNotIn("add", command)
        self.assertEqual(mocked.call_args.kwargs["shell"], False)
        self.assertLessEqual(mocked.call_args.kwargs["timeout"], 2.0)
        self.assertEqual(mocked.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_three_conditions_missing_any_one_prevents_candidate(self) -> None:
        files = [self._file(f"archive/item{index}.txt", NOW_TS - DAY) for index in range(5)]
        no_time = detect_zombies(
            self.root,
            files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "",
        )
        self.assertEqual(no_time.candidates, ())
        self.assertTrue(no_time.undetermined)

        recent_files = [self._file("archive/recent_notes.txt", NOW_TS - 10 * DAY)]
        below_threshold = detect_zombies(
            self.root,
            recent_files,
            HealthOptions(now=NOW, git_mode="off", zombie_days=365),
            text_reader=lambda item: "",
        )
        self.assertEqual(below_threshold.candidates, ())

        target = self._file("archive/target.txt", NOW_TS - 400 * DAY)
        referenced_files = self._spread_files(target)
        referenced = detect_zombies(
            self.root,
            referenced_files,
            HealthOptions(now=NOW, git_mode="off"),
            text_reader=lambda item: "archive/target.txt",
        )
        self.assertFalse(any(item.file_path == target.path for item in referenced.candidates))


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from app.api.security import RepoPathError, resolve_repo_root
from app.api.settings import WebSettings
from app.dashboard.models import (
    CategoryCount,
    DiffProjection,
    ItemReason,
    ModuleCount,
    PathTitle,
    RuleCount,
    TypeCount,
    to_dict,
)
from app.dashboard.service import (
    SnapshotUnavailableError,
    build_overview,
    build_structure,
    list_repos,
    load_snapshot,
    query_issues,
    resolve_dashboard_repo,
    snapshot_key,
)
from app.health.models import (
    DegradedItem,
    HealthFileEntry,
    HealthIssue,
    HealthReport,
    HealthStatus,
    RiskLevel,
    ScanMeta,
    build_summary,
)
from app.readme.models import (
    ReadmeDegraded,
    ReadmeDiff,
    ReadmeReport,
    ReadmeStatus,
    ReadmeUndetermined,
    empty_index,
)

_FIXED_MODULES = (
    "命名与目录检查",
    "代码检查",
    "链接检查",
    "敏感信息与大文件检查",
)


def _issue(
    *,
    rule_id: str = "code-001",
    module: str = "代码检查",
    risk: RiskLevel = RiskLevel.HIGH,
    line_no: int | None = 1,
    message: str = "问题描述",
    suggestion: str = "修复建议",
    excerpt: str | None = None,
) -> HealthIssue:
    return HealthIssue(rule_id, module, risk, line_no, message, suggestion, excerpt)


def _file(path: str, findings: tuple[HealthIssue, ...] = ()) -> HealthFileEntry:
    level = RiskLevel.HIGH if any(item.risk_level is RiskLevel.HIGH for item in findings) else RiskLevel.SUGGESTION
    return HealthFileEntry(path, level, len(findings), findings)


def _health(
    files: tuple[HealthFileEntry, ...] = (),
    *,
    status: HealthStatus = HealthStatus.OK,
    degraded: tuple[DegradedItem, ...] = (),
    warnings: tuple[str, ...] = (),
    scanned_at: str = "2026-01-01T00:00:00+00:00",
    duration_ms: int = 0,
    undetermined: tuple = (),
    zombies: tuple = (),
) -> HealthReport:
    summary = build_summary(
        files=files,
        zombies=zombies,
        undetermined=undetermined,
        degraded=degraded,
        skipped_file_count=0,
    )
    meta = ScanMeta(scanned_at=scanned_at, duration_ms=duration_ms, file_count=len(files))
    return HealthReport(
        status=status,
        meta=meta,
        summary=summary,
        files=files,
        zombie_candidates=zombies,
        undetermined=undetermined,
        degraded=degraded,
        warnings=warnings,
    )


def _readme(**overrides: object) -> ReadmeReport:
    base: dict[str, object] = {
        "status": ReadmeStatus.OK,
        "format_version": "1.0",
        "scan_root": "<repo>",
        "document_count": 0,
        "demo_project_count": 0,
        "demo_project_suspected_count": 0,
        "readme_found": False,
        "readme_path": None,
        "toc_block_found": False,
        "toc_marker_kind": None,
        "index": empty_index(),
        "index_markdown": "",
        "replacement_block": "",
    }
    base.update(overrides)
    return ReadmeReport(**base)  # type: ignore[arg-type]


class DashboardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="repoguard-dashboard-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.base = Path(self.temp_dir)

    # ---------------------------------------------------------------- helpers
    def _dir(self, *parts: str) -> Path:
        path = self.base.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def _load(
        self,
        files: tuple[HealthFileEntry, ...] = (),
        *,
        health: HealthReport | None = None,
        readme: ReadmeReport | None = None,
        readme_enabled: bool = True,
        root: Path | None = None,
    ):
        repo_root = root if root is not None else self._dir("repo")
        health_report = health if health is not None else _health(files)
        readme_report = readme if readme is not None else _readme()
        snapshot = load_snapshot(
            repo_root,
            health_runner=lambda _root: health_report,
            readme_runner=lambda _root: readme_report,
            readme_enabled=readme_enabled,
        )
        return repo_root, snapshot

    def _query(self, snapshot, **overrides: object):
        params: dict[str, object] = {
            "risk_level": "all",
            "source_module": "all",
            "keyword": "",
            "page": 1,
            "page_size": 20,
            "sort_field": "risk_level",
            "order": "asc",
        }
        params.update(overrides)
        return query_issues(snapshot, **params)  # type: ignore[arg-type]

    # T-S01
    def test_list_repos_returns_unique_relative_ids(self):
        first = self._dir("a", "repo")
        second = self._dir("b", "repo")
        settings = WebSettings(allowed_repo_roots=(first, second), default_repo="repo")

        repos = list_repos(settings)

        self.assertEqual(len(repos), 2)
        ids = [item.id for item in repos]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids[0], "repo")
        self.assertRegex(ids[1], r"^repo-[0-9a-f]{8}$")
        for identifier in ids:
            self.assertNotIn(os.sep, identifier)
            self.assertNotIn("/", identifier)
            self.assertNotIn("\\", identifier)
            self.assertNotRegex(identifier, r"^[A-Za-z]:")

    # T-S02
    def test_list_repos_marks_default_once(self):
        alpha = self._dir("alpha")
        beta = self._dir("beta")
        settings = WebSettings(allowed_repo_roots=(alpha, beta), default_repo="beta")

        repos = list_repos(settings)

        defaults = [item for item in repos if item.is_default]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].id, "beta")
        self.assertTrue({item.id: item.is_default for item in repos}["beta"])

    # T-S03
    def test_list_repos_empty_without_roots(self):
        settings = WebSettings(allowed_repo_roots=(), default_repo=None)

        self.assertEqual(list_repos(settings), ())

    # T-S04
    def test_resolve_dashboard_repo_by_token(self):
        root = self._dir("repo")
        settings = WebSettings(allowed_repo_roots=(root,), default_repo="repo")

        resolved = resolve_dashboard_repo("repo", settings)
        expected = resolve_repo_root("repo", settings)

        self.assertEqual(resolved, expected)
        self.assertEqual(resolved, root)
        self.assertTrue(resolved.is_absolute())

    # T-S05
    def test_resolve_dashboard_repo_rejects_parent_segment(self):
        root = self._dir("repo")
        settings = WebSettings(allowed_repo_roots=(root,), default_repo="repo")

        with self.assertRaises(RepoPathError) as raised:
            resolve_dashboard_repo("..\\..\\Windows", settings)

        self.assertEqual(raised.exception.code, "REPO_FORBIDDEN")
        self.assertEqual(raised.exception.status_code, 403)

    # T-S06
    def test_resolve_dashboard_repo_rejects_outside_root(self):
        allowed = self._dir("inside")
        outside = self._dir("outside")
        settings = WebSettings(allowed_repo_roots=(allowed,), default_repo="inside")

        with self.assertRaises(RepoPathError) as raised:
            resolve_dashboard_repo(str(outside), settings)

        self.assertEqual(raised.exception.code, "REPO_FORBIDDEN")
        self.assertEqual(raised.exception.status_code, 403)

    # T-S08 桌面模式：允许白名单之外的本机绝对目录
    def test_desktop_mode_allows_outside_absolute_dir(self):
        outside = self._dir("outside")
        settings = WebSettings(allowed_repo_roots=(), default_repo=None, desktop_mode=True)

        resolved = resolve_repo_root(str(outside), settings)

        self.assertEqual(resolved, outside)

    # T-S09 桌面模式：拒绝相对路径
    def test_desktop_mode_rejects_relative_path(self):
        settings = WebSettings(allowed_repo_roots=(), default_repo=None, desktop_mode=True)

        with self.assertRaises(RepoPathError) as raised:
            resolve_repo_root("some-project", settings)

        self.assertEqual(raised.exception.code, "INVALID_REPO_PATH")

    # T-S10 桌面模式：拒绝不存在的目录
    def test_desktop_mode_rejects_missing_dir(self):
        missing = self.base / "nope"
        settings = WebSettings(allowed_repo_roots=(), default_repo=None, desktop_mode=True)

        with self.assertRaises(RepoPathError) as raised:
            resolve_repo_root(str(missing), settings)

        self.assertEqual(raised.exception.code, "REPO_NOT_FOUND")

    # T-S11 桌面模式：拒绝系统敏感目录
    def test_desktop_mode_rejects_protected_system_dir(self):
        settings = WebSettings(allowed_repo_roots=(), default_repo=None, desktop_mode=True)

        for bad in (r"C:\Windows\System32", r"C:\Program Files\App", r"C:\Program Files (x86)\Tool"):
            with self.assertRaises(RepoPathError) as raised:
                resolve_repo_root(bad, settings)
            self.assertEqual(raised.exception.code, "REPO_FORBIDDEN")

    # T-S12 桌面模式：拒绝上级目录穿越
    def test_desktop_mode_rejects_parent_segment(self):
        settings = WebSettings(allowed_repo_roots=(), default_repo=None, desktop_mode=True)

        with self.assertRaises(RepoPathError) as raised:
            resolve_repo_root(r"C:\Users\anshuai\..\Windows", settings)

        self.assertEqual(raised.exception.code, "REPO_FORBIDDEN")

    # T-S07
    def test_snapshot_key_is_stable_hash(self):
        root = self._dir("repo")
        other = self._dir("other")
        expected = hashlib.sha256(os.path.normcase(str(root.resolve())).encode("utf-8")).hexdigest()

        key = snapshot_key(root)

        self.assertEqual(key, snapshot_key(root))
        self.assertNotEqual(key, snapshot_key(other))
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertEqual(key, expected)

    # T-S08
    def test_load_snapshot_calls_each_runner_once(self):
        root = self._dir("repo")
        health_calls: list[object] = []
        readme_calls: list[object] = []
        health = _health((_file("src/a.py", (_issue(), _issue(rule_id="naming-001", module="命名与目录检查"))),))
        readme = _readme(document_count=2, readme_found=True, readme_path="README.md")

        snapshot = load_snapshot(
            root,
            health_runner=lambda argument: (health_calls.append(argument), health)[1],
            readme_runner=lambda argument: (readme_calls.append(argument), readme)[1],
        )

        self.assertEqual(health_calls, [root])
        self.assertEqual(readme_calls, [root])
        self.assertEqual(snapshot.files_count, 1)
        self.assertEqual(len(snapshot.issues), 2)
        self.assertFalse(snapshot.snapshot.cached)
        self.assertEqual(snapshot.repo.id, root.name)

    # T-S09
    def test_load_snapshot_skips_readme_when_disabled(self):
        readme_calls: list[object] = []
        health = _health((_file("a.py", (_issue(),)),))
        root = self._dir("repo")

        snapshot = load_snapshot(
            root,
            health_runner=lambda _root: health,
            readme_runner=lambda argument: (readme_calls.append(argument), _readme())[1],
            readme_enabled=False,
        )

        self.assertEqual(readme_calls, [])
        self.assertEqual(snapshot.readme.status, ReadmeStatus.PARTIAL_DEGRADED.value)
        self.assertEqual(snapshot.readme.document_count, 0)
        self.assertEqual(snapshot.snapshot.status, HealthStatus.PARTIAL_DEGRADED.value)
        self.assertIn(ItemReason("README 扫描", "已禁用 README 扫描"), snapshot.readme.degraded)
        self.assertIn("已禁用 README 扫描", snapshot.readme.warnings)
        self.assertIn("已禁用 README 扫描", snapshot.snapshot.warnings)

    # T-S10
    def test_load_snapshot_health_input_error_raises(self):
        root = self._dir("repo")
        readme_calls: list[object] = []
        broken = _health(status=HealthStatus.INPUT_ERROR)

        with self.assertRaises(SnapshotUnavailableError):
            load_snapshot(
                root,
                health_runner=lambda _root: broken,
                readme_runner=lambda argument: readme_calls.append(argument),
            )

        self.assertEqual(readme_calls, [])

    # T-S11
    def test_load_snapshot_merges_degraded_and_warnings(self):
        health = _health(
            (),
            degraded=(
                DegradedItem("礼物", "健康A"),
                DegradedItem("链接检查", "超时"),
            ),
            warnings=("w1", "w2"),
        )
        readme = _readme(
            degraded=(
                ReadmeDegraded("链接检查", "超时"),
                ReadmeDegraded("Demo 识别", "无法读取"),
            ),
            warnings=("w2", "w3"),
        )

        _, snapshot = self._load(health=health, readme=readme)

        self.assertEqual(
            snapshot.snapshot.degraded,
            (
                ItemReason("礼物", "健康A"),
                ItemReason("链接检查", "超时"),
                ItemReason("Demo 识别", "无法读取"),
            ),
        )
        self.assertEqual(snapshot.snapshot.warnings, ("w1", "w2", "w3"))
        self.assertEqual(snapshot.snapshot.status, HealthStatus.OK.value)

    # T-S12
    def test_load_snapshot_duration_is_measured_sum(self):
        health = _health((_file("a.py", (_issue(),)),), duration_ms=12)
        readme = _readme(duration_ms=30)

        _, snapshot = self._load(health=health, readme=readme)

        self.assertEqual(snapshot.snapshot.duration_ms, 42)
        self.assertEqual(snapshot.snapshot.duration_ms, health.meta.duration_ms + readme.duration_ms)

    # T-S13
    def test_overview_summary_matches_health(self):
        findings = (
            _issue(rule_id="code-001"),
            _issue(rule_id="code-002", line_no=2),
            _issue(rule_id="naming-001", module="命名与目录检查", risk=RiskLevel.SUGGESTION),
        )
        health = _health((_file("a.py", findings),))
        _, snapshot = self._load(health=health)

        overview = build_overview(snapshot)

        self.assertEqual(
            overview["summary"],
            {
                "issue_count": 3,
                "must_fix_count": 2,
                "suggestion_count": 1,
                "zombie_candidate_count": 0,
                "undetermined_count": 0,
                "skipped_file_count": 0,
                "degraded_count": 0,
            },
        )
        self.assertEqual(overview["files_count"], 1)

    # T-S14
    def test_overview_risk_breakdown(self):
        findings = (
            _issue(rule_id="code-001"),
            _issue(rule_id="code-002", line_no=2),
            _issue(rule_id="naming-001", module="命名与目录检查", risk=RiskLevel.SUGGESTION),
        )
        _, snapshot = self._load(health=_health((_file("a.py", findings),)))

        charts = build_overview(snapshot)["charts"]

        self.assertEqual(charts["risk_breakdown"], {"high": 2, "suggestion": 1})
        flattened_high = sum(1 for item in snapshot.issues if item.risk_level == "高风险")
        flattened_suggestion = sum(1 for item in snapshot.issues if item.risk_level == "建议")
        self.assertEqual(charts["risk_breakdown"], {"high": flattened_high, "suggestion": flattened_suggestion})

    # T-S15
    def test_overview_module_breakdown_has_four_modules(self):
        findings = (
            _issue(rule_id="code-001", module="代码检查"),
            _issue(rule_id="code-002", module="代码检查", line_no=2),
            _issue(rule_id="naming-001", module="命名与目录检查", line_no=3),
            _issue(rule_id="report-001", module="报告", line_no=4),
        )
        _, snapshot = self._load(health=_health((_file("a.py", findings),)))

        breakdown = build_overview(snapshot)["charts"]["module_breakdown"]

        self.assertEqual(
            breakdown,
            (
                ModuleCount("命名与目录检查", 1),
                ModuleCount("代码检查", 2),
                ModuleCount("链接检查", 0),
                ModuleCount("敏感信息与大文件检查", 0),
                ModuleCount("报告", 1),
            ),
        )
        self.assertEqual([item.module for item in breakdown][:4], list(_FIXED_MODULES))

    # T-S15b
    def test_overview_category_breakdown_maps_rules(self):
        findings = (
            _issue(rule_id="code-004", module="代码检查"),
            _issue(rule_id="code-001", module="代码检查", line_no=2),
            _issue(rule_id="naming-002", module="命名与目录检查", line_no=3),
            _issue(rule_id="code-011", module="代码检查", risk=RiskLevel.SUGGESTION, line_no=4),
            _issue(rule_id="link-003", module="链接检查", line_no=5),
            _issue(rule_id="sens-002", module="敏感信息与大文件检查", risk=RiskLevel.SUGGESTION, line_no=6),
            _issue(rule_id="report-001", module="报告", line_no=7),
        )
        _, snapshot = self._load(health=_health((_file("a.py", findings),)))

        breakdown = build_overview(snapshot)["charts"]["category_breakdown"]

        self.assertEqual(
            breakdown,
            (
                CategoryCount("代码质量", 1),
                CategoryCount("安全漏洞", 1),
                CategoryCount("风格问题", 1),
                CategoryCount("文档问题", 2),
                CategoryCount("其他", 2),
            ),
        )

    # T-S16
    def test_overview_file_type_breakdown_has_three_keys(self):
        files = (
            _file("README.md", (_issue(),)),
            _file("main.py", (_issue(rule_id="code-002", line_no=2),)),
            _file("config.ini", (_issue(rule_id="link-001", module="链接检查", line_no=3),)),
            _file("LICENSE", ()),
        )
        _, snapshot = self._load(health=_health(files))

        overview = build_overview(snapshot)

        self.assertEqual(
            overview["charts"]["file_type_breakdown"],
            (
                TypeCount("markdown", 1),
                TypeCount("code", 1),
                TypeCount("other", 2),
            ),
        )
        self.assertEqual(
            sum(item.count for item in overview["charts"]["file_type_breakdown"]),
            overview["files_count"],
        )

    # T-S17
    def test_overview_top_files_order_and_limit(self):
        counts = {
            "f01.py": 5,
            "f02.py": 3,
            "f03.py": 3,
            "f04.py": 2,
            "f05.py": 2,
            "f06.py": 2,
            "f07.py": 1,
            "f08.py": 1,
            "f09.py": 1,
            "f10.py": 1,
            "f11.py": 1,
            "f12.py": 1,
        }
        files = tuple(self._entry(path, count) for path, count in counts.items())
        _, snapshot = self._load(health=_health(files))

        top_files = build_overview(snapshot)["charts"]["top_files"]

        self.assertEqual(len(top_files), 10)
        self.assertEqual(
            [item.file_path for item in top_files],
            ["f01.py", "f02.py", "f03.py", "f04.py", "f05.py", "f06.py", "f07.py", "f08.py", "f09.py", "f10.py"],
        )
        self.assertEqual(
            [(item.issue_count, item.file_path) for item in top_files],
            sorted(
                [(count, path) for path, count in counts.items() if count > 0],
                key=lambda pair: (-pair[0], pair[1]),
            )[:10],
        )

    def _entry(self, path: str, count: int) -> HealthFileEntry:
        findings = tuple(
            _issue(
                rule_id=f"code-{index:03d}",
                line_no=index + 1,
                message=f"{path} 问题 {index}",
            )
            for index in range(count)
        )
        return _file(path, findings)

    # T-S18
    def test_query_issues_default_sort_high_first(self):
        files = (
            _file(
                "b.py",
                (
                    _issue(rule_id="code-001", line_no=None, message="空行号高风险"),
                    _issue(rule_id="code-002", line_no=3, risk=RiskLevel.SUGGESTION, message="建议"),
                ),
            ),
            _file(
                "a.py",
                (
                    _issue(rule_id="code-003", line_no=10, message="行号十"),
                    _issue(rule_id="code-004", line_no=None, message="空行号"),
                ),
            ),
        )
        _, snapshot = self._load(health=_health(files))

        page = self._query(snapshot)

        self.assertEqual(
            [(item.file_path, item.line_no, item.risk_level) for item in page.items],
            [
                ("a.py", 10, "高风险"),
                ("a.py", None, "高风险"),
                ("b.py", None, "高风险"),
                ("b.py", 3, "建议"),
            ],
        )
        risks = [item.risk_level for item in page.items]
        self.assertEqual(risks, sorted(risks, key=lambda value: 0 if value == "高风险" else 1))

    # T-S19
    def test_query_issues_pagination_boundary(self):
        findings = tuple(
            _issue(
                rule_id=f"code-{index:03d}",
                line_no=index + 1,
                risk=RiskLevel.SUGGESTION,
                message=f"建议 {index}",
            )
            for index in range(5)
        )
        _, snapshot = self._load(health=_health((_file("a.py", findings),)))

        last_page = self._query(snapshot, page=3, page_size=2)
        self.assertEqual(last_page.total, 5)
        self.assertEqual(last_page.total_pages, 3)
        self.assertEqual(len(last_page.items), 1)

        overflow = self._query(snapshot, page=999, page_size=2)
        self.assertEqual(overflow.items, ())
        self.assertEqual(overflow.total, 5)
        self.assertEqual(overflow.total_pages, 3)

        empty = self._query(snapshot, risk_level="high")
        self.assertEqual(empty.total, 0)
        self.assertEqual(empty.total_pages, 0)
        self.assertEqual(empty.items, ())

    # T-S20
    def test_query_issues_filter_combination(self):
        files = (
            _file("a.py", (_issue(rule_id="code-001", message="SQL 注入风险"),)),
            _file("c.py", (_issue(rule_id="code-002", line_no=2, message="sql 关键字未转义"),)),
            _file("b.py", (_issue(rule_id="link-001", module="链接检查", line_no=3, message="SQL 链接失效"),)),
            _file(
                "d.py",
                (_issue(rule_id="code-003", line_no=4, risk=RiskLevel.SUGGESTION, message="命名建议"),),
            ),
        )
        _, snapshot = self._load(health=_health(files))

        page = self._query(snapshot, risk_level="high", source_module="代码检查", keyword="sql")

        self.assertEqual(page.total, 2)
        self.assertEqual({item.file_path for item in page.items}, {"a.py", "c.py"})
        self.assertTrue(all(item.risk_level == "高风险" for item in page.items))
        self.assertTrue(all(item.source_module == "代码检查" for item in page.items))
        self.assertTrue(all("sql" in item.message.casefold() for item in page.items))
        self.assertEqual(
            page.filters,
            {"risk_level": "high", "source_module": "代码检查", "keyword": "sql"},
        )

    # T-S21
    def test_query_issues_keyword_case_insensitive_literal(self):
        files = (
            _file("a.py", (_issue(rule_id="code-001", message="包含 .* 字面量"),)),
            _file("b.py", (_issue(rule_id="code-002", line_no=2, message="普通说明"),)),
            _file("c.py", (_issue(rule_id="code-003", line_no=3, message="alpha Beta 说明"),)),
        )
        _, snapshot = self._load(health=_health(files))

        literal = self._query(snapshot, keyword=".*")
        upper = self._query(snapshot, keyword="BETA")

        self.assertEqual(literal.total, 1)
        self.assertEqual(literal.items[0].file_path, "a.py")
        self.assertEqual(literal.filters["keyword"], ".*")
        self.assertEqual(upper.total, 1)
        self.assertEqual(upper.items[0].file_path, "c.py")
        self.assertEqual(upper.filters["keyword"], "BETA")

    # T-S22
    def test_query_issues_charts_and_counts(self):
        rule_counts = {
            "r01": 5,
            "r02": 4,
            "r03": 4,
            "r04": 3,
            "r05": 3,
            "r06": 3,
            "r07": 2,
            "r08": 2,
            "r09": 1,
            "r10": 1,
            "r11": 1,
            "r12": 1,
        }
        findings: list[HealthIssue] = []
        for rule_id, count in rule_counts.items():
            for _ in range(count):
                index = len(findings)
                findings.append(
                    _issue(
                        rule_id=rule_id,
                        module=_FIXED_MODULES[index % 4],
                        risk=RiskLevel.HIGH if index % 2 == 0 else RiskLevel.SUGGESTION,
                        line_no=index + 1,
                        message=f"问题 {rule_id}-{index}",
                    )
                )
        _, snapshot = self._load(health=_health((_file("a.py", tuple(findings)),)))

        page = self._query(snapshot, page_size=100)

        self.assertEqual(
            page.rule_breakdown,
            (
                RuleCount("r01", 5),
                RuleCount("r02", 4),
                RuleCount("r03", 4),
                RuleCount("r04", 3),
                RuleCount("r05", 3),
                RuleCount("r06", 3),
                RuleCount("r07", 2),
                RuleCount("r08", 2),
                RuleCount("r09", 1),
                RuleCount("r10", 1),
            ),
        )
        self.assertEqual(len(page.rule_breakdown), 10)
        self.assertEqual([item.module for item in page.module_risk_matrix], list(_FIXED_MODULES))
        high = sum(1 for item in findings if item.risk_level is RiskLevel.HIGH)
        suggestion = len(findings) - high
        self.assertEqual(
            page.counts,
            {"total": len(findings), "high": high, "suggestion": suggestion},
        )
        self.assertEqual(sum(item.high for item in page.module_risk_matrix), high)
        self.assertEqual(sum(item.suggestion for item in page.module_risk_matrix), suggestion)

    # T-S23
    def test_structure_maps_readme_fields(self):
        markdown = (
            "## 文档索引\n"
            "- **docs**\n"
            "- [入门](docs/guide.md)\n"
            "- [API 文档](<docs/api.md>)\n"
            "\n"
            "## Demo 工程\n"
            "- [演示一](demo/one/)\n"
            "- [演示二](demo/two/) 疑似\n"
        )
        readme = _readme(
            status=ReadmeStatus.OK,
            document_count=3,
            demo_project_count=1,
            demo_project_suspected_count=1,
            readme_found=True,
            readme_path="README.md",
            toc_block_found=True,
            toc_marker_kind="<!-- TOC -->",
            diffs=(ReadmeDiff("新增", "docs/new.md", None, "新文档", None, 3),),
            undetermined=(ReadmeUndetermined("docs/x.md", "无法读取"),),
            degraded=(ReadmeDegraded("链接检查", "超时"),),
            warnings=("w1",),
            index_markdown=markdown,
        )
        _, snapshot = self._load(health=_health((_file("a.py", (_issue(),)),)), readme=readme)

        structure = build_structure(snapshot)
        projection = structure["readme"]

        self.assertEqual(projection.status, "正常")
        self.assertEqual(projection.format_version, "1.0")
        self.assertEqual(projection.document_count, 3)
        self.assertEqual(projection.demo_project_count, 1)
        self.assertEqual(projection.demo_project_suspected_count, 1)
        self.assertTrue(projection.readme_found)
        self.assertEqual(projection.readme_path, "README.md")
        self.assertTrue(projection.toc_block_found)
        self.assertEqual(projection.toc_marker_kind, "<!-- TOC -->")
        self.assertEqual(
            projection.diffs,
            (DiffProjection("新增", "docs/new.md", None, "新文档", None, 3),),
        )
        self.assertEqual(projection.undetermined, (ItemReason("docs/x.md", "无法读取"),))
        self.assertEqual(projection.degraded, (ItemReason("链接检查", "超时"),))
        self.assertEqual(projection.warnings, ("w1",))
        self.assertEqual(projection.index_markdown, markdown)

        document_items = structure["index"].document_section.items
        self.assertEqual([item.kind for item in document_items], ["directory", "document", "document"])
        self.assertEqual([item.path for item in document_items], ["docs/", "docs/guide.md", "docs/api.md"])
        self.assertEqual([item.title for item in document_items], ["docs", "入门", "API 文档"])
        self.assertEqual([item.depth for item in document_items], [0, 0, 0])
        self.assertEqual(document_items[0].link, None)
        self.assertEqual(document_items[1].link, "docs/guide.md")

        demo_items = structure["index"].demo_section.items
        self.assertEqual([item.kind for item in demo_items], ["demo", "demo"])
        self.assertEqual([item.confidence for item in demo_items], ["confirmed", "suspected"])

    # T-S24
    def test_structure_suspected_has_count_only(self):
        markdown = (
            "## 文档索引\n"
            "- [入门](docs/guide.md)\n"
            "\n"
            "## Demo 工程\n"
            "- [演示一](demo/one/)\n"
            "- [演示二](demo/two/) 疑似\n"
        )
        readme = _readme(
            demo_project_count=1,
            demo_project_suspected_count=2,
            index_markdown=markdown,
        )
        _, snapshot = self._load(health=_health((_file("a.py", (_issue(),)),)), readme=readme)

        structure = build_structure(snapshot)
        demo = structure["demo"]

        self.assertEqual(demo.confirmed_items, (PathTitle("demo/one/", "演示一"),))
        self.assertEqual(demo.suspected_count, 2)
        self.assertEqual(demo.suspected_count, readme.demo_project_suspected_count)
        self.assertEqual(set(to_dict(demo).keys()), {"confirmed_items", "suspected_count"})
        self.assertFalse(hasattr(demo, "suspected_items"))
        self.assertFalse(hasattr(demo, "items"))

    # T-S25
    def test_structure_readme_disabled_degraded(self):
        root, snapshot = self._load(readme_enabled=False)

        structure = build_structure(snapshot)
        projection = structure["readme"]

        self.assertEqual(projection.status, ReadmeStatus.PARTIAL_DEGRADED.value)
        self.assertEqual(projection.document_count, 0)
        self.assertEqual(projection.demo_project_count, 0)
        self.assertEqual(projection.demo_project_suspected_count, 0)
        self.assertFalse(projection.readme_found)
        self.assertIsNone(projection.readme_path)
        self.assertEqual(structure["demo"].confirmed_items, ())
        self.assertEqual(structure["demo"].suspected_count, 0)
        self.assertIn(ItemReason("README 扫描", "已禁用 README 扫描"), projection.degraded)
        self.assertEqual(structure["repo"].id, root.name)

    # T-S26
    def test_all_paths_are_relative(self):
        files = (
            _file(r"C:\Users\dev\repo\src\main.py", (_issue(message="m1"),)),
            _file(r"\\server\share\ml\train.py", (_issue(rule_id="code-002", line_no=2, message="m2"),)),
            _file("/home/dev/app/util.py", (_issue(rule_id="code-003", line_no=3, message="m3"),)),
            _file(r"src\ok\fine.py", (_issue(rule_id="code-004", line_no=4, message="m4"),)),
        )
        readme = _readme(
            readme_found=True,
            readme_path=r"C:\Users\dev\repo\README.md",
            diffs=(ReadmeDiff("新增", r"\\server\share\docs\new.md", None, "新文档", None, 1),),
            undetermined=(ReadmeUndetermined("/home/dev/app/unknown.md", "无法判定"),),
            degraded=(ReadmeDegraded(r"C:\Users\dev\repo\legacy", "无法读取"),),
            index_markdown=(
                "## 文档索引\n"
                "- [指南](docs/guide.md)\n"
                "\n"
                "## Demo 工程\n"
                "- [演示](demo/one/) 疑似\n"
            ),
        )
        _, snapshot = self._load(health=_health(files), readme=readme)
        structure = build_structure(snapshot)

        paths: dict[str, str] = {}
        for index, issue in enumerate(snapshot.issues):
            paths[f"issues[{index}].file_path"] = issue.file_path
        for index, item in enumerate(snapshot.top_files):
            paths[f"top_files[{index}].file_path"] = item.file_path
        projection = structure["readme"]
        paths["readme.readme_path"] = projection.readme_path or ""
        paths["readme.diffs[0].path"] = projection.diffs[0].path
        paths["readme.undetermined[0].item"] = projection.undetermined[0].item
        paths["readme.degraded[0].item"] = projection.degraded[0].item
        for index, item in enumerate(structure["index"].document_section.items):
            paths[f"index.document_section.items[{index}].path"] = item.path
            paths[f"index.document_section.items[{index}].link"] = item.link or ""
        for index, item in enumerate(structure["index"].demo_section.items):
            paths[f"index.demo_section.items[{index}].path"] = item.path
            paths[f"index.demo_section.items[{index}].link"] = item.link or ""

        for label, value in paths.items():
            self.assertNotRegex(value, r"^[A-Za-z]:", f"{label} 泄漏盘符：{value}")
            self.assertNotIn("\\", value, f"{label} 含反斜杠：{value}")
            self.assertFalse(value.startswith("/"), f"{label} 是绝对路径：{value}")

        self.assertEqual(
            sorted(item.file_path for item in snapshot.issues),
            ["main.py", "src/ok/fine.py", "train.py", "util.py"],
        )
        self.assertEqual(projection.readme_path, "README.md")
        self.assertEqual(projection.diffs[0].path, "new.md")
        self.assertEqual(projection.undetermined[0].item, "unknown.md")
        self.assertEqual(projection.degraded[0].item, "legacy")


if __name__ == "__main__":
    unittest.main()
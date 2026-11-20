from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from app.api.app import create_app
from app.api.settings import WebSettings
from app.dashboard.cache import CacheBusyError, CacheTimeoutError
from app.dashboard.router import get_cache, get_health_runner, get_readme_runner
from app.dashboard.settings import DashboardSettings
from app.health.models import (
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
from tests.webhook_helpers import WebhookASGIClient, no_network

_DASHBOARD_PATHS = (
    "/api/dashboard/overview",
    "/api/dashboard/issues",
    "/api/dashboard/structure",
    "/api/dashboard/repos",
)

_ISSUE_REQUIRED = {
    "file_path",
    "line_no",
    "rule_id",
    "source_module",
    "risk_level",
    "message",
    "suggestion",
    "excerpt",
}

_README_REQUIRED = {
    "status",
    "format_version",
    "document_count",
    "demo_project_count",
    "demo_project_suspected_count",
    "readme_found",
    "readme_path",
    "toc_block_found",
    "toc_marker_kind",
    "diffs",
    "undetermined",
    "degraded",
    "warnings",
    "index_markdown",
}


class _RaisingCache:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def get_or_load(self, *args: object, **kwargs: object):
        raise self._error


def _issue(
    rule_id: str,
    module: str,
    risk: RiskLevel,
    line_no: int,
    message: str,
) -> HealthIssue:
    return HealthIssue(rule_id, module, risk, line_no, message, "修复建议", "示例片段")


def _file(path: str, findings: tuple[HealthIssue, ...]) -> HealthFileEntry:
    level = RiskLevel.HIGH if any(item.risk_level is RiskLevel.HIGH for item in findings) else RiskLevel.SUGGESTION
    return HealthFileEntry(path, level, len(findings), findings)


def _health_report() -> HealthReport:
    prefixes = {"代码检查": "code", "链接检查": "link", "命名与目录检查": "naming"}
    layout = (("src/a.py", 10, "代码检查"), ("docs/b.md", 8, "链接检查"), ("README.md", 7, "命名与目录检查"))
    files: list[HealthFileEntry] = []
    index = 0
    for path, count, module in layout:
        findings: list[HealthIssue] = []
        for _ in range(count):
            risk = RiskLevel.HIGH if index % 2 == 0 else RiskLevel.SUGGESTION
            findings.append(
                _issue(
                    f"{prefixes[module]}-{index:03d}",
                    module,
                    risk,
                    index + 1,
                    f"{module} 问题 {index}",
                )
            )
            index += 1
        files.append(_file(path, tuple(findings)))
    summary = build_summary(files=tuple(files), zombies=(), undetermined=(), degraded=(), skipped_file_count=0)
    return HealthReport(
        status=HealthStatus.OK,
        meta=ScanMeta(scanned_at="2026-01-01T00:00:00+00:00", duration_ms=7, file_count=len(files)),
        summary=summary,
        files=tuple(files),
    )


def _readme_report() -> ReadmeReport:
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
    return ReadmeReport(
        status=ReadmeStatus.OK,
        format_version="1.0",
        scan_root="<repo>",
        document_count=5,
        demo_project_count=2,
        demo_project_suspected_count=1,
        readme_found=True,
        readme_path="README.md",
        toc_block_found=True,
        toc_marker_kind="<!-- TOC -->",
        index=empty_index(),
        index_markdown=markdown,
        replacement_block="",
        diffs=(ReadmeDiff("新增", "docs/new.md", None, "新文档", None, 3),),
        undetermined=(ReadmeUndetermined("docs/x.md", "无法读取"),),
        degraded=(ReadmeDegraded("链接检查", "超时"),),
        warnings=("w1",),
        scanned_at="2026-01-01T00:00:00+00:00",
        duration_ms=11,
    )


def _tree_state(root: Path) -> dict[str, tuple[str, int]]:
    state: dict[str, tuple[str, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            key = str(path.relative_to(root)).replace("\\", "/")
            state[key] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
    return state


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="repoguard-dashboard-api-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.root = Path(self.temp_dir).resolve()
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
        (self.root / "docs").mkdir(exist_ok=True)
        (self.root / "docs" / "b.md").write_text("# b\n", encoding="utf-8")
        (self.root / "README.md").write_text("# demo\n", encoding="utf-8")

        self.health_report = _health_report()
        self.readme_report = _readme_report()
        self.health_calls: list[object] = []
        self.readme_calls: list[object] = []
        self.app = self._make_app()
        self.client = WebhookASGIClient(self.app)

    def _health_stub(self, repo_root: object) -> HealthReport:
        self.health_calls.append(repo_root)
        return self.health_report

    def _readme_stub(self, repo_root: object) -> ReadmeReport:
        self.readme_calls.append(repo_root)
        return self.readme_report

    def _make_app(self, *, roots=None, default: str | None = None, desktop: bool = False):
        root_tuple = (self.root,) if roots is None else tuple(roots)
        settings = WebSettings(
            allowed_repo_roots=root_tuple,
            default_repo=self.root.name if default is None else default,
            static_dir=self.root,
            desktop_mode=desktop,
        )
        app = create_app(settings)
        app.state.dashboard_settings = DashboardSettings()
        app.dependency_overrides[get_health_runner] = lambda: self._health_stub
        app.dependency_overrides[get_readme_runner] = lambda: self._readme_stub
        return app

    # T-A01
    def test_repos_returns_default_flag(self):
        response = self.client.get("/api/dashboard/repos")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["repos"]), 1)
        descriptor = body["repos"][0]
        self.assertEqual(descriptor["id"], self.root.name)
        self.assertTrue(descriptor["is_default"])
        self.assertEqual(body["default_repo"], descriptor["id"])
        self.assertTrue(body["generated_at"])
        self.assertRegex(body["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    # T-A02
    def test_repos_hides_absolute_paths(self):
        response = self.client.get("/api/dashboard/repos")

        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(str(self.root).replace("\\", "/"), text)
        self.assertNotIn("C:\\Users", text)
        self.assertNotIn("/home/", text)
        self.assertNotRegex(text, r"[A-Za-z]:[\\/]")

    # T-A03b 桌面模式：check-repo 校验通过并返回文件数
    def test_check_repo_success_desktop(self):
        app = self._make_app(desktop=True)
        client = WebhookASGIClient(app)

        response = client.post("/api/dashboard/check-repo", json={"path": str(self.root)})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name"], self.root.name)
        self.assertTrue(body["exists"])
        self.assertTrue(body["is_dir"])
        self.assertGreaterEqual(body["file_count"], 3)

    # T-A03c 桌面模式：check-repo 拒绝不存在的目录
    def test_check_repo_missing_dir(self):
        app = self._make_app(desktop=True)
        client = WebhookASGIClient(app)
        missing = self.root / "nope"

        response = client.post("/api/dashboard/check-repo", json={"path": str(missing)})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "REPO_NOT_FOUND")

    # T-A03d 非桌面模式：check-repo 拒绝白名单外路径
    def test_check_repo_forbidden_outside_root(self):
        outside = Path(self.temp_dir).parent / "repoguard-outside-xyz"
        outside.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, str(outside), True)

        response = self.client.post("/api/dashboard/check-repo", json={"path": str(outside)})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "REPO_FORBIDDEN")

    # T-A03
    def test_overview_success_has_all_required_fields(self):
        response = self.client.get("/api/dashboard/overview")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("repo", "snapshot", "summary", "charts", "files_count", "zombie_candidates_count", "undetermined_count"):
            self.assertIn(key, body)
        self.assertEqual(set(body["repo"]), {"id", "label", "is_default"})
        self.assertEqual(
            set(body["snapshot"]),
            {
                "status",
                "scanned_at",
                "duration_ms",
                "cached",
                "cache_age_seconds",
                "refresh_throttled",
                "ttl_seconds",
                "degraded",
                "warnings",
            },
        )
        self.assertEqual(
            set(body["summary"]),
            {
                "issue_count",
                "must_fix_count",
                "suggestion_count",
                "zombie_candidate_count",
                "undetermined_count",
                "skipped_file_count",
                "degraded_count",
            },
        )
        self.assertEqual(
            set(body["charts"]),
            {"risk_breakdown", "module_breakdown", "category_breakdown", "file_type_breakdown", "top_files"},
        )
        summary = body["summary"]
        self.assertEqual(summary["issue_count"], 25)
        self.assertEqual(summary["must_fix_count"] + summary["suggestion_count"], summary["issue_count"])
        self.assertEqual(body["snapshot"]["duration_ms"], 18)
        self.assertEqual(body["snapshot"]["ttl_seconds"], 60)
        self.assertEqual(body["snapshot"]["status"], "正常")
        self.assertEqual(body["files_count"], 3)
        self.assertEqual(len(body["charts"]["top_files"]), 3)
        self.assertEqual(sum(item["count"] for item in body["charts"]["file_type_breakdown"]), 3)
        self.assertEqual({item["type"] for item in body["charts"]["file_type_breakdown"]}, {"markdown", "code", "other"})

    # T-A04
    def test_overview_second_request_cached(self):
        first = self.client.get("/api/dashboard/overview")
        second = self.client.get("/api/dashboard/overview")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["snapshot"]["cached"])
        cached = second.json()["snapshot"]
        self.assertTrue(cached["cached"])
        self.assertGreaterEqual(cached["cache_age_seconds"], 0)
        self.assertLess(cached["cache_age_seconds"], 60)
        self.assertEqual(len(self.health_calls), 1)
        self.assertEqual(len(self.readme_calls), 1)

    # T-A05
    def test_overview_refresh_throttled(self):
        first = self.client.get("/api/dashboard/overview", params={"refresh": 1})
        second = self.client.get("/api/dashboard/overview", params={"refresh": 1})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["snapshot"]["refresh_throttled"])
        self.assertTrue(second.json()["snapshot"]["refresh_throttled"])
        self.assertTrue(second.json()["snapshot"]["cached"])
        self.assertEqual(len(self.health_calls), 1)

    # T-A06
    def test_issues_invalid_sort_returns_400(self):
        response = self.client.get("/api/dashboard/issues", params={"sort": "password"})

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "INVALID_QUERY_PARAM")
        self.assertEqual(error["detail"], "字段：sort")
        self.assertEqual(self.health_calls, [])

    # T-A07
    def test_issues_invalid_refresh_returns_400(self):
        response = self.client.get("/api/dashboard/issues", params={"refresh": 2})

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "INVALID_QUERY_PARAM")
        self.assertEqual(error["detail"], "字段：refresh")
        self.assertEqual(self.health_calls, [])

    # T-A08
    def test_issues_page_size_over_limit_returns_422(self):
        response = self.client.get("/api/dashboard/issues", params={"page_size": 200})

        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_ERROR")
        self.assertEqual(error["detail"], "字段：page_size")

    # T-A09
    def test_issues_keyword_too_long_returns_400(self):
        response = self.client.get("/api/dashboard/issues", params={"keyword": "国" * 65})

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "INVALID_QUERY_PARAM")
        self.assertEqual(error["detail"], "字段：keyword")
        self.assertEqual(self.health_calls, [])

    # T-A10
    def test_issues_pagination_and_sort_stable(self):
        collected: list[tuple[str, str, int | None]] = []
        lengths: list[int] = []
        for page in (1, 2, 3):
            response = self.client.get("/api/dashboard/issues", params={"page": page, "page_size": 10})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["total"], 25)
            self.assertEqual(body["total_pages"], 3)
            lengths.append(len(body["items"]))
            collected.extend(
                (item["file_path"], item["rule_id"], item["line_no"]) for item in body["items"]
            )

        self.assertEqual(lengths, [10, 10, 5])
        self.assertEqual(len(collected), 25)
        self.assertEqual(len(set(collected)), 25)

        first_page = self.client.get("/api/dashboard/issues", params={"page": 1, "page_size": 10})
        repeated = self.client.get("/api/dashboard/issues", params={"page": 1, "page_size": 10})
        self.assertEqual(first_page.json()["items"], repeated.json()["items"])

    # T-A11
    def test_structure_fields_and_no_suspected_detail(self):
        response = self.client.get("/api/dashboard/structure")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("repo", "snapshot", "readme", "index", "demo"):
            self.assertIn(key, body)
        self.assertEqual(set(body["readme"]), _README_REQUIRED)
        self.assertEqual(body["readme"]["format_version"], "1.0")
        self.assertEqual(body["readme"]["document_count"], 5)
        self.assertEqual(body["readme"]["demo_project_suspected_count"], 1)
        self.assertEqual(set(body["index"]), {"document_section", "demo_section", "root_readme_path"})
        self.assertEqual(set(body["demo"]), {"confirmed_items", "suspected_count"})
        self.assertNotIn("suspected_items", body["demo"])
        self.assertEqual(body["demo"]["suspected_count"], 1)
        self.assertEqual([item["confidence"] for item in body["index"]["demo_section"]["items"]], ["confirmed", "suspected"])
        for item in body["index"]["document_section"]["items"]:
            self.assertEqual(
                set(item),
                {"kind", "path", "title", "depth", "link", "anchor", "confidence"},
            )

    # T-A12
    def test_post_method_returns_405(self):
        for path in _DASHBOARD_PATHS:
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.json()["error"]["code"], "METHOD_NOT_ALLOWED")

    # T-A13
    def test_forbidden_repo_returns_403(self):
        response = self.client.get("/api/dashboard/overview", params={"repo": "..\\..\\Windows"})

        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "REPO_FORBIDDEN")
        self.assertEqual(self.health_calls, [])

    # T-A14
    def test_missing_repo_returns_404(self):
        response = self.client.get("/api/dashboard/overview", params={"repo": "missing-dir"})

        self.assertEqual(response.status_code, 404)
        error = response.json()["error"]
        self.assertEqual(error["code"], "REPO_NOT_FOUND")
        self.assertEqual(self.health_calls, [])

    # T-A15
    def test_busy_returns_429(self):
        app = self._make_app()
        app.dependency_overrides[get_cache] = lambda: _RaisingCache(CacheBusyError("缓存并发已满"))
        client = WebhookASGIClient(app)

        response = client.get("/api/dashboard/overview")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "DASHBOARD_BUSY")
        self.assertEqual(self.health_calls, [])

    # T-A16
    def test_timeout_returns_504(self):
        app = self._make_app()
        app.dependency_overrides[get_cache] = lambda: _RaisingCache(CacheTimeoutError("扫描超时"))
        client = WebhookASGIClient(app)

        response = client.get("/api/dashboard/structure")

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "DASHBOARD_TIMEOUT")
        self.assertEqual(self.health_calls, [])

    # T-A17
    def test_unavailable_returns_503(self):
        app = self._make_app(roots=())
        client = WebhookASGIClient(app)

        overview = client.get("/api/dashboard/overview")
        repos = client.get("/api/dashboard/repos")

        self.assertEqual(overview.status_code, 503)
        self.assertEqual(overview.json()["error"]["code"], "DASHBOARD_UNAVAILABLE")
        self.assertEqual(repos.status_code, 503)
        self.assertEqual(repos.json()["error"]["code"], "DASHBOARD_UNAVAILABLE")
        self.assertEqual(self.health_calls, [])

    # T-A18
    def test_error_body_shape_and_request_id(self):
        response = self.client.get("/api/dashboard/issues", params={"sort": "password"})

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(set(body), {"error", "request_id"})
        self.assertEqual(set(body["error"]), {"code", "message", "detail"})
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])
        self.assertRegex(body["request_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(body["error"]["message"])
        text = response.text
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("ValueError", text)
        self.assertNotIn(".py", text)

    # T-A19
    def test_response_headers_no_store_and_nosniff(self):
        response = self.client.get("/api/dashboard/repos")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("application/json"))
        self.assertIn("charset=utf-8", response.headers["Content-Type"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertRegex(response.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    # T-A20
    def test_requests_do_not_touch_network_or_files(self):
        before = _tree_state(self.root)

        with no_network():
            responses = {path: self.client.get(path) for path in _DASHBOARD_PATHS}

        after = _tree_state(self.root)

        for path, response in responses.items():
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 200)
        self.assertEqual(after, before)
        self.assertEqual(len(self.health_calls), 1)
        self.assertEqual(len(self.readme_calls), 1)


if __name__ == "__main__":
    unittest.main()
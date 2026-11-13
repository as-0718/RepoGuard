from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.rules import sensitive
from app.core.rules.common.config import DEFAULT_CONFIG
from app.core.rules.common.file_io import CheckContext, create_snapshot
from app.core.rules.common.models import ChangeEntry, ChangeStatus, IssueLevel

MB = 1024 * 1024


def _context(root: Path) -> CheckContext:
    return CheckContext(
        repo_root=root,
        config=DEFAULT_CONFIG,
        module_name="sensitive",
        snapshot=lambda path: create_snapshot(root, path, DEFAULT_CONFIG),
    )


def _check_file(root: Path, relative: str, content: str | bytes) -> tuple:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    entry = ChangeEntry(status=ChangeStatus.ADD, path=relative, line_no=1)
    return sensitive.check(entry, _context(root)).findings


class SensitiveTest(unittest.TestCase):
    def test_warn_size(self):
        findings = sensitive.check_file_size(2 * MB, "lab/a.bin", DEFAULT_CONFIG)
        self.assertEqual({item.rule_id for item in findings}, {"sens-001"})
        self.assertEqual(sensitive.check_file_size(900 * 1024, "lab/a.bin", DEFAULT_CONFIG), ())

    def test_fail_size(self):
        findings = sensitive.check_file_size(6 * MB, "lab/a.bin", DEFAULT_CONFIG)
        self.assertEqual({item.rule_id for item in findings}, {"sens-002"})
        self.assertNotIn("sens-002", {item.rule_id for item in sensitive.check_file_size(4 * MB, "lab/a.bin", DEFAULT_CONFIG)})

    def test_binary_size_only(self):
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "assets/big.mp4", b"\x00" * (6 * MB))
        self.assertEqual({item.rule_id for item in findings}, {"sens-002"})
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "assets/big.txt", b"\x00" * (6 * MB) + b"password = \"123456\"")
        self.assertEqual({item.rule_id for item in findings}, {"sens-002"})

    def test_private_key_token(self):
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "ghp_abcdef1234567890\n"
            "AKIAABCDEFGHIJKLMNOP\n"
            "github_pat_abcdefghijklmnopqrstuv\n"
            "glpat-abcdefghij\n"
            "xoxb-abcdefghij\n"
            "sk-abcdefghijklmnopqrstuvwx\n"
            "AIza" + "a" * 35 + "\n"
        )
        findings = sensitive.scan_secrets(text, "lab/a.txt", DEFAULT_CONFIG)
        rules = {item.rule_id for item in findings}
        self.assertIn("sens-003", rules)
        self.assertIn("sens-004", rules)

    def test_password_conn(self):
        text = 'password = "123456"\nmysql://user:pass@host/db\n'
        self.assertIn("sens-005", {item.rule_id for item in sensitive.scan_secrets(text, "lab/a.txt", DEFAULT_CONFIG)})

    def test_entropy_advice(self):
        findings = sensitive.scan_secrets("a" * 40 + "\n", "lab/a.txt", DEFAULT_CONFIG)
        self.assertIn("sens-006", {item.rule_id for item in findings})
        self.assertIs([item for item in findings if item.rule_id == "sens-006"][0].level, IssueLevel.SUGGESTION)
        self.assertNotIn("sens-006", {item.rule_id for item in sensitive.scan_secrets("abc123xy\n", "lab/a.txt", DEFAULT_CONFIG)})

    def test_mask(self):
        self.assertEqual(sensitive.mask_secret("ghp_abcdef123456"), "ghp_****")
        self.assertEqual(sensitive.mask_secret("abc"), "****")
        findings = sensitive.scan_secrets('token = "ghp_abcdef123456"\n', "lab/a.txt", DEFAULT_CONFIG)
        joined = "".join(item.message + item.suggestion + (item.excerpt or "") for item in findings)
        self.assertNotIn("ghp_abcdef123456", joined)

    def test_size_boundary(self):
        self.assertEqual(sensitive.check_file_size(MB, "lab/a.bin", DEFAULT_CONFIG), ())
        five = sensitive.check_file_size(5 * MB, "lab/a.bin", DEFAULT_CONFIG)
        self.assertNotIn("sens-002", {item.rule_id for item in five})

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(_check_file(root, "notes/empty.txt", ""), ())

    def test_aggregation(self):
        text = "".join('token = "ghp_abcdef123456"\n' for _ in range(5))
        findings = [item for item in sensitive.scan_secrets(text, "lab/a.txt", DEFAULT_CONFIG) if item.rule_id == "sens-004"]
        self.assertEqual(len(findings), 1)
        self.assertIn("共 5 处", findings[0].message)

    def test_placeholder_exemption(self):
        findings = sensitive.scan_secrets('示例占位 token = "ghp_abcdef123456"\n', "lab/a.txt", DEFAULT_CONFIG)
        token_findings = [item for item in findings if item.rule_id == "sens-004"]
        self.assertTrue(token_findings)
        self.assertIs(token_findings[0].level, IssueLevel.SUGGESTION)
        pem_findings = sensitive.scan_secrets("示例占位\n-----BEGIN RSA PRIVATE KEY-----\n", "lab/a.txt", DEFAULT_CONFIG)
        self.assertIs([item for item in pem_findings if item.rule_id == "sens-003"][0].level, IssueLevel.MUST_FIX)

    def test_placeholder_exclusions(self):
        text = (
            'password = "${VAR}"\n'
            'password = os.getenv("PWD")\n'
            'password = "<your password>"\n'
            'password = "{{PASSWORD}}"\n'
            'password = "your_password"\n'
            'password = "请输入密码"\n'
            'password = "****"\n'
        )
        self.assertNotIn("sens-005", {item.rule_id for item in sensitive.scan_secrets(text, "lab/a.txt", DEFAULT_CONFIG)})

    def test_binary_no_text_match(self):
        with tempfile.TemporaryDirectory() as temp:
            findings = _check_file(Path(temp), "assets/a.bin", b"\x00password = '123456'")
        self.assertNotIn("sens-005", {item.rule_id for item in findings})

    def test_no_high_entropy_duplicate(self):
        text = 'token = "ghp_abcdef1234567890abcdef1234567890"\n'
        findings = sensitive.scan_secrets(text, "lab/a.txt", DEFAULT_CONFIG)
        self.assertIn("sens-004", {item.rule_id for item in findings})
        self.assertNotIn("sens-006", {item.rule_id for item in findings})

    def test_no_network_no_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "lab/a.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('token = "ghp_abcdef123456"\n', encoding="utf-8")
            before = sorted(item.name for item in root.rglob("*"))
            with patch("socket.socket", side_effect=AssertionError("不应发起网络请求")):
                _check_file(root, "lab/a.txt", 'token = "ghp_abcdef123456"\n')
            after = sorted(item.name for item in root.rglob("*"))
        self.assertEqual(before, after)

    def test_deleted_skip(self):
        def explode(path):
            raise AssertionError("D 状态不应读取文件")

        entry = ChangeEntry(status=ChangeStatus.DELETE, path="lab/a.txt", line_no=1)
        context = CheckContext(Path("."), DEFAULT_CONFIG, "sensitive", explode)
        self.assertEqual(sensitive.check(entry, context).findings, ())

    def test_missing_file_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = ChangeEntry(status=ChangeStatus.ADD, path="lab/missing.txt", line_no=1)
            result = sensitive.check(entry, _context(root))
        self.assertEqual(result.findings, ())
        self.assertIn("无法获取文件信息", result.skip_reason or "")

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "lab/a.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("hello\n", encoding="utf-8")
            entry = ChangeEntry(status=ChangeStatus.ADD, path="lab/a.txt", line_no=1)
            with patch("app.core.rules.sensitive.scan_secrets", return_value=()):
                with patch("app.core.rules.sensitive.time.perf_counter", side_effect=[0.0, 2.0]):
                    result = sensitive.check(entry, _context(root))
        self.assertIn("sens-007", {item.rule_id for item in result.findings})

    def test_no_real_credentials(self):
        sample = Path(__file__).parent / "fixtures" / "sample_changes.txt"
        text = sample.read_text(encoding="utf-8")
        self.assertNotIn("AKIA", text)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", text)


if __name__ == "__main__":
    unittest.main()
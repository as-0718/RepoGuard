from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.app import create_app
from app.api.settings import WebSettings
from app.fixer import backup as backup_module
from tests.webhook_helpers import WebhookASGIClient, no_network


class FixerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="repoguard-fixer-api-")
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.base = Path(self.temp_dir).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.backup_dir = self.base / "backups"
        self.backup_dir.mkdir()
        self.settings = WebSettings(
            desktop_mode=True,
            allowed_repo_roots=(self.repo,),
            default_repo=self.repo.name,
            static_dir=self.repo,
            db_path=self.base / "repoguard.db",
        )
        self.app = create_app(self.settings)
        self.client = WebhookASGIClient(self.app)

    def _write(self, relative: str, text: str, encoding: str = "utf-8") -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return path

    def _write_bytes(self, relative: str, data: bytes) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _issue(self, file_path: str, line_no: int = 1, rule_id: str = "link-005") -> dict[str, object]:
        return {"file_path": file_path, "line_no": line_no, "rule_id": rule_id, "excerpt": ""}

    def _selection(self, file_path: str, old_line: str, line_no: int = 1, rule_id: str = "link-005") -> dict[str, object]:
        return {"file_path": file_path, "line_no": line_no, "rule_id": rule_id, "old_line": old_line}

    def _preview(self, issues: list[dict[str, object]], strict: bool = False):
        body = {"repo": str(self.repo), "issues": issues, "strict": strict}
        with no_network():
            return self.client.post("/api/fixer/preview", json=body)

    def _apply(
        self,
        selections: list[dict[str, object]],
        *,
        on_stale: str = "skip",
        strict: bool = False,
        backup_dir: Path | None = None,
    ):
        body = {
            "repo": str(self.repo),
            "backup_dir": str(backup_dir or self.backup_dir),
            "selections": selections,
            "on_stale": on_stale,
            "strict": strict,
        }
        with no_network():
            return self.client.post("/api/fixer/apply", json=body)

    def _rollback(
        self,
        backup_id: str,
        backups: list[dict[str, object]],
        *,
        force: bool = False,
        strict: bool = False,
    ):
        body = {
            "repo": str(self.repo),
            "backup_dir": str(self.backup_dir),
            "backup_id": backup_id,
            "backups": backups,
            "force": force,
            "strict": strict,
        }
        with no_network():
            return self.client.post("/api/fixer/rollback", json=body)

    def test_preview_link005_inline_image_definition(self) -> None:
        self._write("docs/inline.md", "详见[说明](docs/a b.md)\n")
        self._write("docs/image.md", '![图片](assets/图 片.png "标题")\n')
        self._write("docs/definition.md", '[参考]: docs/a b.md "网站标题"\n')
        response = self._preview(
            [
                self._issue("docs/inline.md"),
                self._issue("docs/image.md"),
                self._issue("docs/definition.md"),
            ]
        )
        self.assertEqual(response.status_code, 200)
        patches = response.json()["patches"]
        self.assertEqual(len(patches), 3)
        self.assertTrue(all(item["fixable"] for item in patches))
        self.assertIn("docs/a%20b.md", patches[0]["new_line"])
        self.assertIn("assets/图%20片.png", patches[1]["new_line"])
        self.assertIn('"标题"', patches[1]["new_line"])
        self.assertIn("docs/a%20b.md", patches[2]["new_line"])
        self.assertIn('"网站标题"', patches[2]["new_line"])

    def test_preview_angle_wrapped_and_missing_target_not_fixable(self) -> None:
        self._write("docs/angle.md", "[x](<./lab 03.md>)\n")
        self._write("docs/missing.md", "[x](./no-space.md)\n")
        self._write("docs/short.md", "hello\n")
        response = self._preview(
            [
                self._issue("docs/angle.md"),
                self._issue("docs/missing.md"),
                self._issue("docs/short.md", line_no=5),
            ]
        )
        self.assertEqual(response.status_code, 200)
        patches = response.json()["patches"]
        self.assertEqual(len(patches), 3)
        self.assertFalse(any(item["fixable"] for item in patches))
        self.assertTrue(all(item["reason"] for item in patches))

    def test_preview_non_whitelisted_rule_not_fixable(self) -> None:
        self._write("docs/plain.md", "[x](./a b.md)\n")
        response = self._preview([self._issue("docs/plain.md", rule_id="link-001")])
        self.assertEqual(response.status_code, 200)
        patch = response.json()["patches"][0]
        self.assertFalse(patch["fixable"])
        self.assertIn("非白名单", patch["reason"])

    def test_preview_rejects_file_path_outside_repo(self) -> None:
        for file_path in ("../outside.md", str(self.base / "outside.md")):
            with self.subTest(file_path=file_path):
                response = self._preview([self._issue(file_path)])
                self.assertIn(response.status_code, (400, 403))
                self.assertIn(
                    response.json()["error"]["code"],
                    {"FIXER_INVALID_SELECTION", "REPO_FORBIDDEN", "INVALID_REPO_PATH"},
                )

    def test_preview_rejects_symlink_escape(self) -> None:
        self._write("docs/link.md", "[x](./a b.md)\n")
        real_lstat = os.lstat

        def fake_lstat(path: object) -> os.stat_result:
            if Path(path).name == "link.md":
                return os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            return real_lstat(path)

        with patch("app.fixer.paths.os.lstat", side_effect=fake_lstat):
            response = self._preview([self._issue("docs/link.md")])
        self.assertEqual(response.status_code, 200)
        patch_body = response.json()["patches"][0]
        self.assertFalse(patch_body["fixable"])
        self.assertIn("符号链接", patch_body["reason"])

    def test_backup_dir_inside_repo_rejected(self) -> None:
        self._write("docs/a.md", "[x](./a b.md)\n")
        inside = self.repo / "inside-backups"
        inside.mkdir()
        response = self._apply(
            [self._selection("docs/a.md", "[x](./a b.md)")],
            backup_dir=inside,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FIXER_BACKUP_DIR_FORBIDDEN")

    def test_apply_backs_up_before_write_and_bytes_match(self) -> None:
        path = self._write("docs/a.md", "[x](./a b.md)\n")
        original = path.read_bytes()
        response = self._apply([self._selection("docs/a.md", "[x](./a b.md)")])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(len(body["backups"]), 1)
        record = body["backups"][0]
        backup_path = self.backup_dir / record["backup_path"]
        self.assertEqual(backup_path.read_bytes(), original)
        updated = path.read_bytes()
        self.assertNotEqual(updated, original)
        self.assertIn(b"%20", updated)
        self.assertEqual(record["after_sha256"], hashlib.sha256(updated).hexdigest())

    def test_apply_stale_old_line_skipped(self) -> None:
        path = self._write("docs/a.md", "[x](./a b.md)\n")
        original = path.read_bytes()
        stale = self._selection("docs/a.md", "[x](./old b.md)")
        response = self._apply([stale])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["applied"], [])
        self.assertEqual(len(body["skipped"]), 1)
        self.assertIn("已过期", body["skipped"][0]["reason"])
        self.assertEqual(path.read_bytes(), original)

        rejected = self._apply([stale], on_stale="reject")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "FIXER_STALE_PATCH")
        self.assertEqual(path.read_bytes(), original)

    def test_apply_multi_patch_same_file_backs_up_once(self) -> None:
        path = self._write("docs/multi.md", "[a](./a b.md)\n[b](./c d.md)\n")
        response = self._apply(
            [
                self._selection("docs/multi.md", "[a](./a b.md)", line_no=1),
                self._selection("docs/multi.md", "[b](./c d.md)", line_no=2),
            ]
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["applied"]), 2)
        self.assertEqual(len(body["backups"]), 1)
        text = path.read_text(encoding="utf-8")
        self.assertIn("[a](./a%20b.md)", text)
        self.assertIn("[b](./c%20d.md)", text)

    def test_apply_same_line_multiple_links_single_patch(self) -> None:
        self._write("docs/same-line.md", "[a](./a b.md) and [b](./c d.md)\n")
        response = self._preview([self._issue("docs/same-line.md")])
        self.assertEqual(response.status_code, 200)
        patches = response.json()["patches"]
        self.assertEqual(len(patches), 1)
        self.assertTrue(patches[0]["fixable"])
        self.assertEqual(patches[0]["new_line"].count("%20"), 2)

    def test_rollback_restores_original_bytes(self) -> None:
        path = self._write("docs/a.md", "[x](./a b.md)\n")
        original = path.read_bytes()
        applied = self._apply([self._selection("docs/a.md", "[x](./a b.md)")])
        self.assertEqual(applied.status_code, 200)
        body = applied.json()
        response = self._rollback(body["backup_id"], body["backups"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["restored"]), 1)
        self.assertEqual(path.read_bytes(), original)

    def test_rollback_backup_path_escape_rejected(self) -> None:
        self._write("docs/a.md", "[x](./a b.md)\n")
        applied = self._apply([self._selection("docs/a.md", "[x](./a b.md)")])
        self.assertEqual(applied.status_code, 200)
        backup_id = applied.json()["backup_id"]
        for backup_path in ("../../outside.md", str(self.base / "outside.md")):
            with self.subTest(backup_path=backup_path):
                response = self._rollback(
                    backup_id,
                    [{"file_path": "docs/a.md", "backup_path": backup_path}],
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "FIXER_BACKUP_PATH_FORBIDDEN")

    def test_rollback_detects_manual_modification(self) -> None:
        path = self._write("docs/a.md", "[x](./a b.md)\n")
        applied = self._apply([self._selection("docs/a.md", "[x](./a b.md)")])
        self.assertEqual(applied.status_code, 200)
        body = applied.json()
        path.write_text("manual\n", encoding="utf-8")
        response = self._rollback(body["backup_id"], body["backups"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["restored"], [])
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertIn("手工修改", response.json()["failed"][0]["reason"])
        self.assertEqual(path.read_text(encoding="utf-8"), "manual\n")

    def test_apply_undecodable_and_unwritable_skipped(self) -> None:
        gbk = self._write_bytes("docs/gbk.md", "[x](./a b.md) 中文\n".encode("gbk"))
        binary = self._write_bytes("docs/binary.md", b"\xff\xfe\x00\x00")
        readonly = self._write("docs/readonly.md", "[x](./a b.md)\n")
        good = self._write("docs/good.md", "[x](./g o.md)\n")
        os.chmod(readonly, stat.S_IREAD)
        self.addCleanup(os.chmod, readonly, stat.S_IWRITE)

        real_atomic = backup_module.atomic_write

        def fake_atomic(path: Path, data: bytes) -> None:
            if path.name == "readonly.md":
                raise PermissionError("read-only")
            real_atomic(path, data)

        with patch("app.fixer.backup.atomic_write", side_effect=fake_atomic):
            response = self._apply(
                [
                    self._selection("docs/gbk.md", "[x](./a b.md)"),
                    self._selection("docs/binary.md", "[x](./a b.md)"),
                    self._selection("docs/readonly.md", "[x](./a b.md)"),
                    self._selection("docs/good.md", "[x](./g o.md)"),
                ]
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(len(body["skipped"]), 3)
        skipped_files = {item["file_path"] for item in body["skipped"]}
        self.assertEqual(skipped_files, {"docs/gbk.md", "docs/binary.md", "docs/readonly.md"})
        self.assertIn("%20", good.read_text(encoding="utf-8"))
        self.assertEqual(gbk.read_bytes(), "[x](./a b.md) 中文\n".encode("gbk"))
        self.assertEqual(binary.read_bytes(), b"\xff\xfe\x00\x00")
        self.assertEqual(readonly.read_text(encoding="utf-8"), "[x](./a b.md)\n")


if __name__ == "__main__":
    unittest.main()
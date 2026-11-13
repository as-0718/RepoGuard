from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.shared.repo_walk import (
    RootValidationError,
    WalkOptions,
    WalkedFile,
    relative_posix,
    resolve_default_repo,
    to_manifest,
    validate_repo_root,
    walk_repository,
)


class RepoWalkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write(self, relative: str, content: str = "x") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_default_repo_prefers_base_then_parent(self) -> None:
        base = self.root / "backend"
        base.mkdir()
        parent_candidate = self.root / "demo-repo"
        parent_candidate.mkdir()
        self.assertEqual(resolve_default_repo(base), parent_candidate.resolve())

        child_candidate = base / "demo-repo"
        child_candidate.mkdir()
        self.assertEqual(resolve_default_repo(base), child_candidate.resolve())

    def test_explicit_root_recurses_nested_directories(self) -> None:
        self._write("a/b/c.txt")
        self._write("a/d.py")
        self._write("top.md")
        result = walk_repository(self.root)
        self.assertEqual([item.path for item in result.files], ["a/b/c.txt", "a/d.py", "top.md"])
        self.assertEqual(result.directory_count, 3)

    def test_skip_technical_directories(self) -> None:
        for name in (".git", "node_modules", "__pycache__", "venv", "dist", "demo.egg-info"):
            self._write(f"{name}/inside.txt")
        self._write("keep.txt")
        result = walk_repository(self.root)
        paths = {item.path for item in result.files}
        self.assertEqual(paths, {"keep.txt"})
        self.assertTrue(any(item.category == "跳过目录" for item in result.skipped))

    def test_hidden_files_and_hidden_directories_are_included(self) -> None:
        self._write(".env", "TOKEN=demo")
        self._write(".gitignore", "*.pyc")
        self._write(".github/workflows/ci.yml", "name: ci")
        result = walk_repository(self.root)
        paths = {item.path for item in result.files}
        self.assertEqual(paths, {".env", ".gitignore", ".github/workflows/ci.yml"})

    def test_depth_limit_stops_deeper_directories(self) -> None:
        self._write("a/b/ok.txt")
        self._write("a/b/c/deep.txt")
        result = walk_repository(self.root, WalkOptions(max_depth=2))
        paths = {item.path for item in result.files}
        self.assertIn("a/b/ok.txt", paths)
        self.assertNotIn("a/b/c/deep.txt", paths)
        self.assertTrue(any(item.category == "深度超限" for item in result.skipped))

    def test_max_files_marks_exceeded_and_stops_early(self) -> None:
        for name in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"):
            self._write(name)
        result = walk_repository(self.root, WalkOptions(max_files=3))
        self.assertTrue(result.exceeded_max_files)
        self.assertEqual(result.max_files, 3)
        self.assertEqual(result.file_count, 3)
        self.assertTrue(any(item.category == "文件上限" for item in result.skipped))

    def test_directory_symlink_is_not_followed(self) -> None:
        target = self.root / "target"
        target.mkdir()
        (target / "inside.txt").write_text("x", encoding="utf-8")
        link = self.root / "link"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Windows 未授予创建符号链接权限，无法验证目录符号链接跳过逻辑")
        result = walk_repository(self.root)
        self.assertNotIn("link/inside.txt", {item.path for item in result.files})
        self.assertTrue(any(item.path == "link" and "符号链接" in item.reason for item in result.skipped))

    def test_file_symlink_is_skipped_with_reason(self) -> None:
        target = self._write("target.txt")
        link = self.root / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("Windows 未授予创建符号链接权限，无法验证文件符号链接跳过逻辑")
        result = walk_repository(self.root)
        self.assertNotIn("link.txt", {item.path for item in result.files})
        self.assertTrue(any(item.path == "link.txt" and "符号链接" in item.reason for item in result.skipped))

    def test_relative_posix_uses_forward_slashes(self) -> None:
        target = self._write("a/b/file.txt")
        relative = relative_posix(self.root, target)
        self.assertEqual(relative, "a/b/file.txt")
        self.assertNotIn("\\", relative)
        self.assertNotIn(":", relative)

    def test_manifest_keeps_spaces_in_path(self) -> None:
        item = WalkedFile("lab/uart/UART Demo-v2.C", self.root / "UART Demo-v2.C", 1, 0.0, ".C")
        self.assertEqual(to_manifest([item]), "M lab/uart/UART Demo-v2.C\n")

    def test_manifest_skips_newline_in_path(self) -> None:
        item = WalkedFile("bad\nname.txt", self.root / "bad", 1, 0.0, ".txt")
        self.assertEqual(to_manifest([item]), "")

    def test_manifest_paths_are_relative_and_safe(self) -> None:
        self._write("docs/readme.md")
        self._write("main.py")
        manifest = to_manifest(walk_repository(self.root).files)
        lines = manifest.splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.startswith("M "))
            relative = line[2:]
            self.assertNotIn("..", relative.split("/"))
            self.assertFalse(relative.startswith("/"))
            self.assertNotIn("\\", relative)
            self.assertFalse(len(relative) > 1 and relative[1] == ":")

    def test_invalid_root_missing(self) -> None:
        with self.assertRaises(RootValidationError) as raised:
            validate_repo_root(self.root / "missing")
        self.assertIn("不存在", raised.exception.reason)

    def test_invalid_root_not_directory(self) -> None:
        path = self._write("file.txt")
        with self.assertRaises(RootValidationError) as raised:
            validate_repo_root(path)
        self.assertIn("不是目录", raised.exception.reason)

    def test_tool_source_root_is_rejected(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        with self.assertRaises(RootValidationError) as raised:
            validate_repo_root(project_root)
        self.assertIn("工具自身源码", raised.exception.reason)
        demo_repo = project_root / "demo-repo"
        self.assertEqual(validate_repo_root(demo_repo), demo_repo.resolve())

    def test_file_metadata_failure_is_skipped(self) -> None:
        class _BrokenEntry:
            name = "broken.txt"
            path = str(self.root / "broken.txt")

            def is_symlink(self) -> bool:
                return False

            def is_dir(self, follow_symlinks: bool = False) -> bool:
                return False

            def is_file(self, follow_symlinks: bool = False) -> bool:
                return True

            def stat(self, follow_symlinks: bool = False):
                raise OSError("denied")

        with patch("app.shared.repo_walk.os.scandir", return_value=[_BrokenEntry()]):
            result = walk_repository(self.root)
        self.assertEqual(result.files, ())
        self.assertTrue(any("元数据无法读取" in item.reason for item in result.skipped))

    def test_directory_read_failure_is_recorded(self) -> None:
        with patch("app.shared.repo_walk.os.scandir", side_effect=PermissionError("denied")):
            result = walk_repository(self.root)
        self.assertEqual(result.files, ())
        self.assertTrue(any("目录无法读取" in item.reason for item in result.skipped))

    def test_encoding_file_is_still_listed_without_reading(self) -> None:
        path = self.root / "gb.md"
        path.write_bytes("# 串口通信实验\n".encode("gb18030"))
        result = walk_repository(self.root)
        self.assertEqual([item.path for item in result.files], ["gb.md"])
        self.assertGreater(result.files[0].size, 0)


if __name__ == "__main__":
    unittest.main()
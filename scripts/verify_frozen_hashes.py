"""RepoGuard 冻结文件哈希与 app.py 增量校验。

读取 .codeartsdoer/evidence/stage5/hashes.txt（sha256 + 两空格 + 仓库相对路径），
逐个重算 SHA-256 并比对；同时用标准库 difflib 比对 evidence/stage5/app.py.orig，
确认 backend/app/api/app.py 仅新增 2 行、删除 0 行。

只使用 Python 标准库；退出码：0 全部一致；1 存在差异；2 文件缺失。
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HASHES = ROOT / ".codeartsdoer" / "evidence" / "stage5" / "hashes.txt"
DEFAULT_APP = ROOT / "backend" / "app" / "api" / "app.py"
DEFAULT_APP_BASELINE = ROOT / ".codeartsdoer" / "evidence" / "stage6" / "app.py.stage6.orig"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_hashes(path: Path) -> list[tuple[str, Path]]:
    if not path.is_file():
        raise FileNotFoundError(f"哈希清单不存在：{path}")
    entries: list[tuple[str, Path]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"哈希清单第 {line_no} 行格式不合法")
        expected, relative = parts
        entries.append((expected.lower(), ROOT / relative.strip()))
    return entries


def check_hashes(path: Path) -> int:
    entries = parse_hashes(path)
    mismatches = 0
    missing = 0
    for expected, file_path in entries:
        relative = file_path.relative_to(ROOT).as_posix()
        if not file_path.is_file():
            print(f"MISSING {relative}")
            missing += 1
            continue
        actual = sha256_file(file_path)
        if actual == expected:
            print(f"OK {relative}")
        else:
            print(f"MISMATCH {relative} expected={expected[:12]} actual={actual[:12]}")
            mismatches += 1
    print(f"\n校验文件数 = {len(entries)}，不符项 = {mismatches}，缺失项 = {missing}")
    if missing:
        return 2
    if mismatches:
        return 1
    return 0


def check_app_increment(app_path: Path, baseline_path: Path) -> int:
    if not app_path.is_file() or not baseline_path.is_file():
        print(f"MISSING app.py 或基线：{app_path} / {baseline_path}")
        return 2
    baseline = baseline_path.read_text(encoding="utf-8").splitlines()
    current = app_path.read_text(encoding="utf-8").splitlines()
    diff = list(
        difflib.unified_diff(
            baseline,
            current,
            fromfile="app.py.orig",
            tofile="app.py",
            lineterm="",
        )
    )
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    print(
        f"APP_PY added={added} removed={removed} "
        f"baseline_lines={len(baseline)} current_lines={len(current)}"
    )
    for line in diff:
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            print(f"  {line}")
    return 0 if (added == 2 and removed == 0) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冻结文件 SHA-256 与 app.py 增量校验")
    parser.add_argument("--hashes", type=Path, default=DEFAULT_HASHES, help="哈希清单路径")
    parser.add_argument("--app", type=Path, default=DEFAULT_APP, help="当前 app.py 路径")
    parser.add_argument(
        "--app-baseline",
        type=Path,
        default=DEFAULT_APP_BASELINE,
        help="app.py 基线路径",
    )
    parser.add_argument("--skip-app-check", action="store_true", help="跳过 app.py 增量校验")
    args = parser.parse_args(argv)

    try:
        hash_rc = check_hashes(args.hashes)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR {exc}")
        return 2

    app_rc = 0
    if not args.skip_app_check:
        app_rc = check_app_increment(args.app, args.app_baseline)

    if hash_rc == 2 or app_rc == 2:
        return 2
    if hash_rc == 1 or app_rc == 1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
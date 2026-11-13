from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Sequence

from ..shared.repo_walk import RootValidationError, is_within_root
from .models import ReadmeOptions
from .render import readme_to_json, render_readme_text
from .service import exit_code_for, run_readme_scan


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.readme.cli",
        description="RepoGuard README 目录生成：只读扫描并输出索引、差异与替换片段。",
    )
    parser.add_argument("--repo", default=None, help="仓库根目录，默认查找 demo-repo")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    parser.add_argument("--readme", default=None, help="README 文件路径，必须在仓库根内")
    parser.add_argument("--output", default=None, help="额外写入 JSON 报告，必须在仓库根之外")
    parser.add_argument("--max-files", type=int, default=5000, help="文件数上限，30～50000")
    parser.add_argument("--debug", action="store_true", help="输出调试堆栈到标准错误")
    return parser


def parse_readme_options(args: argparse.Namespace) -> tuple[ReadmeOptions, tuple[str, ...]]:
    if args.max_files < 30 or args.max_files > 50000:
        raise ValueError("文件数上限必须在 30～50000 之间")
    return ReadmeOptions(max_files=args.max_files, readme_path=args.readme), tuple()


def validate_output_path(root: str | Path, output: str | Path, readme_path: str | Path | None) -> str | None:
    try:
        target = Path(output).expanduser().resolve(strict=False)
    except OSError:
        return "输出文件路径无法解析"
    if is_within_root(root, target):
        return "输出文件必须位于被巡检仓库之外"
    if readme_path is not None:
        try:
            readme = Path(readme_path).expanduser().resolve(strict=False)
        except OSError:
            return "README 路径无法解析"
        if target == readme:
            return "输出文件不得覆盖 README"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        options, _ = parse_readme_options(args)
    except ValueError as exc:
        print(f"参数错误：{exc}")
        return 2

    try:
        from .service import input_error_report
        from ..shared.repo_walk import resolve_default_repo

        root = Path(args.repo) if args.repo is not None else resolve_default_repo(Path.cwd() / "backend")
        from ..shared.repo_walk import validate_repo_root

        root = validate_repo_root(root)
    except RootValidationError as exc:
        print(f"输入存在错误，本次 README 扫描未执行：{exc.reason}")
        return 2

    if args.output is not None:
        readme_path = args.readme
        if readme_path is not None:
            from .compare import locate_readme

            located = locate_readme(root, readme_path)
            readme_path = str(located) if located is not None else readme_path
        error = validate_output_path(root, args.output, readme_path)
        if error:
            print(f"输入存在错误，本次 README 扫描未执行：{error}")
            return 2

    try:
        report = run_readme_scan(args.repo, options)
    except Exception:
        if args.debug:
            print("以下为调试信息，可忽略", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        print("README 目录扫描执行异常，未能完成，请稍后重试。")
        return 3
    output_text = readme_to_json(report) if args.format == "json" else render_readme_text(report)
    print(output_text)
    if args.output is not None:
        try:
            Path(args.output).write_text(readme_to_json(report), encoding="utf-8")
        except OSError:
            print(f"无法写入输出文件：{args.output}")
            return 3
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
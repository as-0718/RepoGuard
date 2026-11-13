from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Sequence

from ..core.rules.common.config import build_config
from ..shared.repo_walk import RootValidationError, is_within_root
from .models import HealthOptions, resolve_options
from .render import health_to_json, render_health_text
from .service import exit_code_for, resolve_repo_root, run_health_check


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.health.cli",
        description="RepoGuard 全仓健康巡检：只读离线扫描仓库并输出结构化报告。",
    )
    parser.add_argument("--repo", default=None, help="仓库根目录，默认查找 demo-repo")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    parser.add_argument("--output", default=None, help="额外写入 JSON 报告，必须在仓库根之外")
    parser.add_argument("--zombie-days", type=int, default=365, help="僵尸判定阈值，30～3650 天")
    parser.add_argument("--git", choices=("auto", "on", "off"), default="auto", help="Git 依据模式")
    parser.add_argument("--max-files", type=int, default=5000, help="文件数上限，30～50000")
    parser.add_argument("--config", default=None, help="JSON 规则配置文件")
    parser.add_argument("--debug", action="store_true", help="输出调试堆栈到标准错误")
    return parser


def parse_health_options(args: argparse.Namespace) -> tuple[HealthOptions, tuple[str, ...]]:
    if args.max_files < 30 or args.max_files > 50000:
        raise ValueError("文件数上限必须在 30～50000 之间")
    options = HealthOptions(
        zombie_days=args.zombie_days,
        git_mode=args.git,
        max_files=args.max_files,
    )
    return resolve_options(options)


def validate_output_path(root: str | Path, output: str | Path) -> str | None:
    try:
        target = Path(output).expanduser().resolve(strict=False)
    except OSError:
        return "输出文件路径无法解析"
    if is_within_root(root, target):
        return "输出文件必须位于被巡检仓库之外"
    if target.exists() and target.is_dir():
        return "输出路径已存在目录，请输入文件路径"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        options, option_warnings = parse_health_options(args)
    except ValueError as exc:
        print(f"参数错误：{exc}")
        return 2

    try:
        root = resolve_repo_root(args.repo)
    except RootValidationError as exc:
        print(f"输入存在错误，本次巡检未执行：{exc.reason}")
        return 2

    if args.output is not None:
        output_error = validate_output_path(root, args.output)
        if output_error:
            print(f"输入存在错误，本次巡检未执行：{output_error}")
            return 2

    config_warnings: tuple[str, ...] = ()
    rule_config = None
    if args.config:
        built = build_config(config_file=args.config)
        rule_config = built.config
        config_warnings = built.warnings

    try:
        report = run_health_check(args.repo, options, rule_config)
    except Exception:
        if args.debug:
            print("以下为调试信息，可忽略", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        print("全仓健康巡检执行异常，未能完成，请稍后重试。")
        return 3
    warnings = report.warnings + option_warnings + config_warnings
    if warnings != report.warnings:
        from dataclasses import replace

        report = replace(report, warnings=warnings)

    output_text = health_to_json(report) if args.format == "json" else render_health_text(report)
    print(output_text)

    if args.output is not None:
        try:
            Path(args.output).write_text(health_to_json(report), encoding="utf-8")
        except OSError:
            print(f"无法写入输出文件：{args.output}")
            return 3
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
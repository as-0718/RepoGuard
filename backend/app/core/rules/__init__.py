from __future__ import annotations

from typing import Any

__all__: tuple[str, ...] = (
    "run_check",
    "run_check_file",
    "render_text",
    "report_to_dict",
    "report_to_json",
    "CheckReport",
    "CheckSummary",
    "FileGroup",
    "Finding",
    "ChangeEntry",
    "IssueLevel",
    "ReportStatus",
    "ExitCode",
    "RuleConfig",
    "DEFAULT_CONFIG",
)

_ENGINE_EXPORTS = {"run_check", "run_check_file"}
_REPORT_EXPORTS = {"render_text", "report_to_dict", "report_to_json"}
_MODEL_EXPORTS = {
    "CheckReport", "CheckSummary", "FileGroup", "Finding",
    "ChangeEntry", "IssueLevel", "ReportStatus", "ExitCode",
}


def __getattr__(name: str) -> Any:
    if name in _ENGINE_EXPORTS:
        from .engine import run_check, run_check_file

        globals().update({"run_check": run_check, "run_check_file": run_check_file})
        return globals()[name]
    if name in _REPORT_EXPORTS:
        from .common.report import render_text, report_to_dict, report_to_json

        globals().update(
            {
                "render_text": render_text,
                "report_to_dict": report_to_dict,
                "report_to_json": report_to_json,
            }
        )
        return globals()[name]
    if name in _MODEL_EXPORTS:
        from .common import models

        globals().update({item: getattr(models, item) for item in _MODEL_EXPORTS})
        return globals()[name]
    if name in {"RuleConfig", "DEFAULT_CONFIG"}:
        from .common.config import DEFAULT_CONFIG, RuleConfig

        globals().update({"RuleConfig": RuleConfig, "DEFAULT_CONFIG": DEFAULT_CONFIG})
        return globals()[name]
    raise AttributeError(f"模块 app.core.rules 没有属性 {name}")
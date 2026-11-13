from __future__ import annotations

import math
import re
import time
from collections import Counter
from typing import TYPE_CHECKING

from .common.file_io import CheckContext
from .common.models import (
    ChangeEntry,
    ChangeStatus,
    IssueLevel,
    ModuleResult,
    make_finding,
    merge_findings,
)

if TYPE_CHECKING:
    from .common.config import RuleConfig

HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
CREDENTIAL_ASSIGN_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|token|secret|api_key|apikey|access_key)\b\s*[:=]\s*[\"'][^\"'\n]{1,}[\"']"
)
SECRET_EXCLUDE_WORDS = ("${", "os.getenv", "<", "{{", "your_", "****", "请输入")
CONNECTION_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^:/\s]+:[^@\s]+@[^/\s]+")


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def check_file_size(
    size_bytes: int,
    file_path: str,
    config: "RuleConfig",
) -> tuple:
    warn_bytes = int(config.large_file_warn_mb * 1024 * 1024)
    fail_bytes = int(config.large_file_fail_mb * 1024 * 1024)
    size_mb = size_bytes / (1024 * 1024)
    if size_bytes > fail_bytes:
        return (
            make_finding(
                level=IssueLevel.MUST_FIX,
                file_path=file_path,
                message=f"文件体积为 {size_mb:.1f} MB，超过仓库允许的 5 MB 上限",
                suggestion="把文件移出仓库改用外部存储链接，或使用 Git LFS 管理大文件",
                rule_id="sens-002",
            ),
        )
    if size_bytes > warn_bytes:
        return (
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=file_path,
                message=f"文件体积为 {size_mb:.1f} MB，会增加其他同学克隆仓库的时间",
                suggestion="压缩或拆分文件，必要时使用 Git LFS 管理",
                rule_id="sens-001",
            ),
        )
    return ()


def mask_secret(value: str) -> str:
    if len(value) > 4:
        return value[:4] + "****"
    return "****"


def is_placeholder_context(
    line: str,
    start: int,
    end: int,
    config: "RuleConfig",
) -> bool:
    window = line[max(0, start - 80):min(len(line), end + 80)].lower()
    return any(word.lower() in window for word in config.placeholder_context_words)


def _entropy(value: str) -> float:
    counts = Counter(value)
    total = len(value)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _has_enough_categories(value: str) -> bool:
    categories = 0
    if any(char.islower() for char in value):
        categories += 1
    if any(char.isupper() for char in value):
        categories += 1
    if any(char.isdigit() for char in value):
        categories += 1
    if any(not char.isalnum() for char in value):
        categories += 1
    return categories >= 3


def _aggregate(
    rule_id: str,
    records: list[tuple[int, str, IssueLevel]],
    file_path: str,
    description: str,
    suggestion: str,
) -> object | None:
    if not records:
        return None
    records.sort(key=lambda item: item[0])
    lines = [item[0] for item in records]
    level = IssueLevel.MUST_FIX if any(item[2] is IssueLevel.MUST_FIX for item in records) else IssueLevel.SUGGESTION
    first_value = records[0][1]
    if len(records) > 3:
        message = f"{description}，共 {len(records)} 处，涉及行号：{', '.join(str(line) for line in lines[:3])} 等"
    else:
        message = f"{description}，涉及行号：{', '.join(str(line) for line in lines)}"
    return make_finding(
        level=level,
        file_path=file_path,
        message=message,
        suggestion=suggestion,
        rule_id=rule_id,
        line_no=lines[0],
        excerpt=mask_secret(first_value),
    )


def scan_secrets(
    text: str,
    file_path: str,
    config: "RuleConfig",
) -> tuple:
    records: dict[str, list[tuple[int, str, IssueLevel]]] = {
        "sens-003": [], "sens-004": [], "sens-005": [], "sens-006": [],
    }
    claimed_spans: list[tuple[int, int]] = []
    claimed_lines: set[int] = set()
    lines = text.splitlines()

    for spec in config.secret_patterns:
        if spec.rule_id not in records or spec.rule_id == "sens-005":
            continue
        for match in spec.pattern.finditer(text):
            value = match.group(0)
            line_no = _line_of(text, match.start())
            line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
            column = len(text[:match.start()].split("\n")[-1])
            level = spec.level
            if spec.rule_id == "sens-004" and spec.exemptable and is_placeholder_context(
                line_text, column, column + len(value), config
            ):
                level = IssueLevel.SUGGESTION
            if spec.rule_id == "sens-006":
                if line_no in claimed_lines:
                    continue
            records[spec.rule_id].append((line_no, value, level))
            claimed_spans.append((match.start(), match.end()))
            claimed_lines.add(line_no)

    for match in ENTROPY_RE.finditer(text):
        value = match.group(0)
        if any(start < match.end() and match.start() < end for start, end in claimed_spans):
            continue
        if len(value) < 32 or not _has_enough_categories(value) or _entropy(value) < 3.5:
            continue
        line_no = _line_of(text, match.start())
        records["sens-006"].append((line_no, value, IssueLevel.SUGGESTION))
        claimed_lines.add(line_no)

    for match in CREDENTIAL_ASSIGN_RE.finditer(text):
        value = match.group(0)
        if any(word in value for word in SECRET_EXCLUDE_WORDS):
            continue
        line_no = _line_of(text, match.start())
        level = IssueLevel.MUST_FIX
        line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        column = len(text[:match.start()].split("\n")[-1])
        if is_placeholder_context(line_text, column, column + len(value), config):
            level = IssueLevel.SUGGESTION
        records["sens-005"].append((line_no, value, level))
        claimed_lines.add(line_no)

    for match in CONNECTION_RE.finditer(text):
        value = match.group(0)
        line_no = _line_of(text, match.start())
        level = IssueLevel.MUST_FIX
        line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        column = len(text[:match.start()].split("\n")[-1])
        if is_placeholder_context(line_text, column, column + len(value), config):
            level = IssueLevel.SUGGESTION
        records["sens-005"].append((line_no, value, level))
        claimed_lines.add(line_no)

    findings = []
    aggregated = (
        _aggregate(
            "sens-003", records["sens-003"], file_path,
            "检测到 PEM 私钥内容，属于高危敏感信息",
            "立即移除私钥并轮换凭据，改用环境变量或密钥管理服务",
        ),
        _aggregate(
            "sens-004", records["sens-004"], file_path,
            "检测到疑似访问令牌或 API 密钥，属于高危敏感信息",
            "立即移除并轮换令牌，改用环境变量或配置模板占位",
        ),
        _aggregate(
            "sens-005", records["sens-005"], file_path,
            "检测到疑似明文口令或连接串，属于敏感信息",
            "改用环境变量读取或配置模板占位，不要提交真实口令",
        ),
        _aggregate(
            "sens-006", records["sens-006"], file_path,
            "检测到较长随机字符串，可能为密钥或令牌",
            "若为示例请标注占位说明；若为真实凭据请立即移除并轮换",
        ),
    )
    for item in aggregated:
        if item is not None:
            findings.append(item)
    return tuple(findings)


def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult:
    if entry.status is ChangeStatus.DELETE:
        return ModuleResult()

    snapshot = ctx.snapshot(entry.path)
    if snapshot.read_error is not None and snapshot.size == 0:
        return ModuleResult(skip_reason="无法获取文件信息，已跳过")

    size_findings = list(check_file_size(snapshot.size, entry.path, ctx.config))
    if snapshot.size == 0 or snapshot.is_binary:
        return ModuleResult(findings=tuple(size_findings))

    text_result = snapshot.text()
    if text_result.text is None:
        return ModuleResult(
            findings=tuple(size_findings),
            skip_reason="文件内容无法解码，已跳过敏感信息检查",
        )

    started = time.perf_counter()
    secret_findings = list(scan_secrets(text_result.text, entry.path, ctx.config))
    elapsed = time.perf_counter() - started
    if elapsed > ctx.config.large_text_scan_timeout_s:
        secret_findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=entry.path,
                message="文件过大，仅完成体积检查，内容扫描可能不完整",
                suggestion="建议拆分文件，或仅对改动较小的文件执行完整检查",
                rule_id="sens-007",
            )
        )

    merged = merge_findings(
        size_findings + secret_findings,
        max_per_rule_per_file=ctx.config.max_findings_per_rule_per_file,
        module_label="敏感信息与大文件检查",
    )
    return ModuleResult(findings=tuple(merged))
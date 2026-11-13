from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
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

INLINE_RE = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\n]*)\)")
REFERENCE_RE = re.compile(r"\[([^\]\n]*)\]\[([^\]\n]*)\]")
DEFINITION_RE = re.compile(r"^\s*\[([^\]\n]+)\]:\s*(\S.*)?$")
BARE_RE = re.compile(r"https?://[^\s<>\)\]]+")
MALFORMED_RE = re.compile(r"!?\[[^\]\n]*\]\(")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True, slots=True)
class LinkRecord:
    line_no: int
    raw: str
    target: str
    kind: str
    text: str | None = None
    reference_id: str | None = None


def strip_code_blocks(text: str) -> str:
    lines = text.splitlines()
    in_fence = False
    fence_char = ""
    fence_length = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
            lines[index] = ""
            continue
        if in_fence:
            lines[index] = ""
        else:
            lines[index] = re.sub(r"`[^`\n]*`", lambda item: " " * len(item.group(0)), line)
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return result


def extract_links(text: str) -> tuple[LinkRecord, ...]:
    records: list[tuple[int, LinkRecord]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        spans: list[tuple[int, int]] = []

        for match in INLINE_RE.finditer(line):
            spans.append((match.start(), match.end()))
            kind = "image" if match.group(1) == "!" else "inline"
            records.append(
                (
                    match.start(),
                    LinkRecord(
                        line_no=line_no,
                        raw=match.group(0)[:60],
                        target=match.group(3).strip(),
                        kind=kind,
                        text=match.group(2),
                    ),
                )
            )

        for match in REFERENCE_RE.finditer(line):
            spans.append((match.start(), match.end()))
            text_part = match.group(1)
            reference_id = match.group(2) or text_part
            records.append(
                (
                    match.start(),
                    LinkRecord(
                        line_no=line_no,
                        raw=match.group(0)[:60],
                        target="",
                        kind="reference",
                        text=text_part,
                        reference_id=reference_id,
                    ),
                )
            )

        for match in BARE_RE.finditer(line):
            if any(start <= match.start() < end for start, end in spans):
                continue
            records.append(
                (
                    match.start(),
                    LinkRecord(
                        line_no=line_no,
                        raw=match.group(0)[:60],
                        target=match.group(0),
                        kind="bare",
                    ),
                )
            )

        definition = DEFINITION_RE.match(line)
        if definition:
            target = (definition.group(2) or "").strip()
            if target:
                target = target.split()[0]
            records.append(
                (
                    definition.start(),
                    LinkRecord(
                        line_no=line_no,
                        raw=line.strip()[:60],
                        target=target,
                        kind="definition",
                        reference_id=definition.group(1),
                    ),
                )
            )
        elif MALFORMED_RE.search(line) and not INLINE_RE.search(line):
            records.append(
                (
                    MALFORMED_RE.search(line).start(),
                    LinkRecord(
                        line_no=line_no,
                        raw=line.strip()[:60],
                        target="",
                        kind="inline",
                    ),
                )
            )

    records.sort(key=lambda item: (item[1].line_no, item[0]))
    return tuple(record for _, record in records)


def _is_private_host(host: str) -> bool:
    host = host.split(":")[0].strip("[]")
    if host in ("localhost", "127.0.0.1"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _candidate(
    rule_id: str,
    level: IssueLevel,
    message: str,
    suggestion: str,
    link: LinkRecord,
) -> tuple[tuple[int, int], tuple[str, IssueLevel, str, str, LinkRecord]]:
    order = 0 if level is IssueLevel.MUST_FIX else 1
    return (order, int(rule_id.split("-")[1])), (rule_id, level, message, suggestion, link)


def validate_links(
    links: tuple[LinkRecord, ...],
    file_path: str,
    config: "RuleConfig",
) -> tuple:
    definitions = {link.reference_id for link in links if link.kind == "definition" and link.reference_id}
    findings = []
    decorated: list[tuple[tuple[int, int], tuple[str, IssueLevel, str, str, LinkRecord]]] = []

    for link in links:
        if link.kind == "reference":
            if link.reference_id not in definitions:
                decorated.append(
                    _candidate(
                        "link-003",
                        IssueLevel.MUST_FIX,
                        f"引用式链接的标识 {link.reference_id} 在全文没有定义，链接无法解析",
                        f"补充定义 [{link.reference_id}]: ./目标文件.md，或改为行内链接 [文字](./目标文件.md)",
                        link,
                    )
                )
            continue

        target = link.target.strip()
        wrapped = target.startswith("<") and target.endswith(">")
        if wrapped:
            target = target[1:-1].strip()

        if link.kind in ("inline", "image") and "(" in link.raw and not link.raw.rstrip().endswith(")"):
            decorated.append(
                _candidate(
                    "link-002",
                    IssueLevel.MUST_FIX,
                    "链接缺少右括号，Markdown 结构不完整导致无法渲染",
                    "补齐缺失的右括号，并把链接合并到同一行",
                    link,
                )
            )
            continue

        if not target and link.kind in ("inline", "image", "definition"):
            decorated.append(
                _candidate(
                    "link-001",
                    IssueLevel.MUST_FIX,
                    "链接目标为空，读者点击后无法跳转到任何位置",
                    "补全目标路径，例如 ./lab03.md，或删除该链接",
                    link,
                )
            )
            continue

        if " " in target and not wrapped:
            decorated.append(
                _candidate(
                    "link-005",
                    IssueLevel.MUST_FIX,
                    "链接目标包含空格且未用尖括号包裹，可能被解析为无效地址",
                    "把空格编码为 %20，或写成 [说明](<./lab 03.md>)",
                    link,
                )
            )
            continue

        must_fix_candidates = []
        suggest_candidates = []

        if re.match(r"^[A-Za-z]:", target) or target.lower().startswith("file:///") or "c:/users" in target.lower():
            suggest_candidates.append(
                _candidate(
                    "link-004",
                    IssueLevel.SUGGESTION,
                    "链接使用了本机绝对路径，在其他同学电脑上会失效",
                    "改为仓库内相对路径，例如 ./lab03.md",
                    link,
                )
            )

        host = ""
        if re.match(r"^https?://", target):
            host = re.sub(r"^https?://", "", target).split("/")[0]
        elif link.kind == "bare":
            host = re.sub(r"^https?://", "", target).split("/")[0]

        if (
            target.lower().startswith("http://")
            or _is_private_host(host)
            or (link.kind in ("inline", "image") and not (link.text or "").strip())
        ):
            suggest_candidates.append(
                _candidate(
                    "link-006",
                    IssueLevel.SUGGESTION,
                    "链接协议或地址可能影响协作访问，建议优先使用 https 或相对路径",
                    "把 http 改为 https，内网地址改为公开说明或相对路径，并补充链接文字",
                    link,
                )
            )

        if CJK_RE.search(target) or "../" in target:
            suggest_candidates.append(
                _candidate(
                    "link-007",
                    IssueLevel.SUGGESTION,
                    "链接目标包含中文或指向仓库外，跨设备协作时可能失效",
                    "中文建议进行 URL 编码，仓库外目标建议改为仓库内相对路径",
                    link,
                )
            )

        if must_fix_candidates:
            decorated.append(min(must_fix_candidates, key=lambda item: item[0]))
        elif suggest_candidates:
            decorated.append(min(suggest_candidates, key=lambda item: item[0]))

    decorated.sort(key=lambda item: item[0])
    emitted: list = []
    seen_pairs: set[tuple[int, str]] = set()
    seen_link_006 = False
    for _, payload in decorated:
        rule_id, level, message, suggestion, link = payload
        key = (link.line_no, rule_id)
        if key in seen_pairs:
            continue
        if rule_id == "link-006":
            if seen_link_006:
                continue
            seen_link_006 = True
        seen_pairs.add(key)
        emitted.append(
            make_finding(
                level=level,
                file_path=file_path,
                message=message,
                suggestion=suggestion,
                rule_id=rule_id,
                line_no=link.line_no,
                excerpt=link.raw,
            )
        )

    merged = merge_findings(
        emitted,
        max_per_rule_per_file=config.max_findings_per_rule_per_file,
        module_label="链接检查",
    )
    return tuple(merged)


def check(entry: ChangeEntry, ctx: CheckContext) -> ModuleResult:
    if entry.status is ChangeStatus.DELETE or not entry.path.lower().endswith(".md"):
        return ModuleResult()

    snapshot = ctx.snapshot(entry.path)
    if snapshot.is_binary:
        return ModuleResult(skip_reason="Markdown 内容无法解码，已跳过链接检查")
    text_result = snapshot.text()
    if text_result.text is None:
        return ModuleResult(skip_reason="Markdown 内容无法解码，已跳过链接检查")

    stripped = strip_code_blocks(text_result.text)
    links = extract_links(stripped)
    findings = list(validate_links(links, entry.path, ctx.config))

    if len(links) > ctx.config.link_max_per_file:
        issue_count = len(findings)
        findings.append(
            make_finding(
                level=IssueLevel.SUGGESTION,
                file_path=entry.path,
                message=f"该文件共 {len(links)} 条链接，其中 {issue_count} 条存在格式问题",
                suggestion="链接数量较多，建议按章节拆分文档，便于维护和定位问题",
                rule_id="link-008",
            )
        )

    findings.sort(key=lambda item: (item.line_no is None, item.line_no or 0, item.rule_id))
    return ModuleResult(findings=tuple(findings))
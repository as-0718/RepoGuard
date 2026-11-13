from __future__ import annotations

import datetime
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..shared.repo_walk import WalkedFile
from ..shared.text_io import is_binary_path, read_text_for_scan
from .models import DegradedItem, HealthOptions, RiskLevel, UndeterminedItem, ZombieCandidate

DEFAULT_ZOMBIE_DAYS: int = 365
MIN_ZOMBIE_DAYS: int = 30
MAX_ZOMBIE_DAYS: int = 3650
BATCH_WINDOW_SECONDS: float = 3600.0
BATCH_RATIO: float = 0.8
GIT_TIMEOUT_PER_FILE: float = 2.0
GIT_TOTAL_BUDGET: float = 30.0
GENERIC_BASENAMES: frozenset[str] = frozenset({
    "readme.md", "license", ".gitignore", ".gitattributes", "requirements.txt",
    "pyproject.toml", "setup.py", "makefile", "cmakelists.txt", "package.json",
    "index.html", "main.py", "app.py", "main.c",
})
REFERENCE_SUFFIXES: frozenset[str] = frozenset({
    ".md", ".py", ".c", ".h", ".cpp", ".js", ".ts", ".java", ".go", ".txt",
    ".json", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".csv", ".sh", ".bat",
    ".cmake", ".gradle", ".xml", ".html", ".css", ".rst",
})
DEMO_HINT_WORDS: tuple[str, ...] = ("demo", "example", "sample", "tutorial")
BINARY_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
    ".mp4", ".avi", ".mov", ".mp3", ".wav", ".zip", ".gz", ".tar", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".dll",
    ".so", ".bin", ".class", ".pyc", ".o", ".a",
)
STRONG_ENTRY_FILES: frozenset[str] = frozenset({
    "main.py", "app.py", "manage.py", "index.html", "main.c", "main.cpp",
    "main.java", "main.go",
})
STRONG_BUILD_FILES: frozenset[str] = frozenset({
    "requirements.txt", "pyproject.toml", "setup.py", "package.json",
    "pom.xml", "build.gradle", "cmakelists.txt", "makefile", "cargo.toml", "go.mod",
})


@dataclass(frozen=True, slots=True)
class GitActivity:
    available: bool
    timestamp: float | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class GitBudget:
    deadline: float

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    referenced: frozenset[str]
    complete: bool
    unreadable_count: int
    unreadable_items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ZombieResult:
    candidates: tuple[ZombieCandidate, ...] = ()
    undetermined: tuple[UndeterminedItem, ...] = ()
    degraded: tuple[DegradedItem, ...] = ()
    mtime_credible: bool = True
    git_used: bool = False
    reference_complete: bool = True


def is_git_work_tree(root: str | Path) -> bool:
    try:
        return (Path(root) / ".git").exists()
    except OSError:
        return False


def get_git_last_commit(
    root: str | Path,
    relative_path: str,
    *,
    timeout_s: float = GIT_TIMEOUT_PER_FILE,
    budget: GitBudget | None = None,
) -> GitActivity:
    if budget is not None and budget.remaining() <= 0:
        return GitActivity(False, None, "Git 查询超出总预算")
    timeout = timeout_s if budget is None else min(timeout_s, budget.remaining())
    if timeout <= 0:
        return GitActivity(False, None, "Git 查询超出总预算")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    command = [
        "git", "--no-pager", "--no-optional-locks", "-C", str(root),
        "log", "-1", "--format=%ct", "--", relative_path,
    ]
    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return GitActivity(False, None, "Git 不在 PATH 中")
    except subprocess.TimeoutExpired:
        return GitActivity(False, None, "Git 最近提交时间查询超时")
    except OSError:
        return GitActivity(False, None, "Git 最近提交时间查询失败")
    if completed.returncode != 0:
        return GitActivity(False, None, "Git 最近提交时间查询失败")
    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return GitActivity(False, None, "文件没有 Git 提交历史")
    try:
        return GitActivity(True, float(int(raw)), None)
    except ValueError:
        return GitActivity(False, None, "Git 提交时间格式无法识别")


def evaluate_mtime_credibility(files: Sequence[WalkedFile]) -> tuple[bool, str | None]:
    if len(files) < 2:
        return True, None
    values = sorted(item.mtime for item in files)
    best = 0
    right = 0
    for left in range(len(values)):
        while right < len(values) and values[right] - values[left] <= BATCH_WINDOW_SECONDS:
            right += 1
        best = max(best, right - left)
    if best / len(values) >= BATCH_RATIO:
        return False, "文件修改时间疑似批量检出，超过 80% 文件集中在 1 小时窗口"
    return True, None


def is_generic_basename(relative_path: str) -> bool:
    name = Path(relative_path).name.casefold()
    return name in GENERIC_BASENAMES or len(name) < 4


def zombie_exemption_reason(relative_path: str) -> str | None:
    name = Path(relative_path).name.casefold()
    if is_generic_basename(relative_path):
        return "入口或配置文件不适用僵尸判定"
    if name in STRONG_ENTRY_FILES or name in STRONG_BUILD_FILES:
        return "入口或构建文件不适用僵尸判定"
    lowered = relative_path.casefold()
    if any(word in lowered for word in DEMO_HINT_WORDS):
        return "示例文件不参与僵尸判定"
    if name.startswith(".env") or name.startswith(".git"):
        return "配置文件不适用僵尸判定"
    return None


def collect_reference_counts(
    root: str | Path,
    candidates: Sequence[str],
    files: Sequence[WalkedFile],
    *,
    reader: Callable[[WalkedFile], str | None] | None = None,
) -> ReferenceResult:
    if not candidates:
        return ReferenceResult(frozenset(), True, 0, ())
    needles: dict[str, str] = {}
    for path in candidates:
        needles[path] = path
    patterns = sorted({re.escape(item) for item in needles.values()}, key=len, reverse=True)
    matcher = re.compile("|".join(patterns)) if patterns else None
    referenced: set[str] = set()
    unreadable: list[str] = []
    if matcher is None:
        return ReferenceResult(frozenset(), True, 0, ())
    for item in files:
        if item.suffix.casefold() not in REFERENCE_SUFFIXES:
            continue
        if is_binary_path(item.absolute_path, BINARY_SUFFIXES):
            continue
        if reader is not None:
            text = reader(item)
        else:
            text = read_text_for_scan(item.absolute_path).text
        if text is None:
            unreadable.append(item.path)
            if len(unreadable) >= 20:
                break
            continue
        for match in matcher.finditer(text):
            hit = match.group(0)
            for candidate, needle in needles.items():
                if hit == needle and item.path != candidate:
                    referenced.add(candidate)
    return ReferenceResult(
        frozenset(referenced),
        len(unreadable) == 0,
        len(unreadable),
        tuple(sorted(unreadable)),
    )


def compute_idle_days(last_activity_ts: float, now_ts: float) -> int:
    return max(0, int((now_ts - last_activity_ts) // 86400))


def format_activity_date(last_activity_ts: float) -> str:
    return datetime.datetime.fromtimestamp(last_activity_ts, tz=datetime.timezone.utc).date().isoformat()


def detect_zombies(
    root: str | Path,
    files: Sequence[WalkedFile],
    options: HealthOptions,
    text_reader: Callable[[WalkedFile], str | None] | None = None,
) -> ZombieResult:
    if not options.enable_zombie or options.zombie_days <= 0:
        return ZombieResult(degraded=(DegradedItem("僵尸判定", "已禁用僵尸判定"),))
    mtime_credible, mtime_reason = evaluate_mtime_credibility(files)
    now_ts = options.now.timestamp() if options.now is not None else time.time()
    candidates: list[str] = []
    undetermined: list[UndeterminedItem] = []
    degraded: list[DegradedItem] = []
    for item in files:
        reason = zombie_exemption_reason(item.path)
        if reason is not None:
            undetermined.append(UndeterminedItem(item.path, reason))
            continue
        if is_binary_path(item.absolute_path, BINARY_SUFFIXES):
            continue
        candidates.append(item.path)
    if not candidates:
        return ZombieResult(tuple(), tuple(undetermined), tuple(degraded), mtime_credible)

    time_map: dict[str, tuple[float, str]] = {}
    git_used = False
    git_available = options.git_mode != "off" and is_git_work_tree(root)
    if options.git_mode != "off" and git_available:
        budget = GitBudget(time.monotonic() + GIT_TOTAL_BUDGET)
        for path in candidates:
            activity = get_git_last_commit(root, path, budget=budget)
            if activity.available and activity.timestamp is not None:
                time_map[path] = (activity.timestamp, "git")
                git_used = True
            elif budget.remaining() <= 0:
                degraded.append(DegradedItem("Git", "Git 查询超出 30 秒预算，已改用文件修改时间"))
                break
            else:
                degraded.append(DegradedItem(path, activity.reason or "Git 最近提交时间查询失败"))
        if not git_used:
            degraded.append(DegradedItem("Git", "Git 历史不可用，已改用文件修改时间"))
    elif options.git_mode != "off":
        degraded.append(DegradedItem("Git", "仓库不是 Git 工作区，已改用文件修改时间"))

    for item in files:
        if item.path not in candidates or item.path in time_map:
            continue
        if mtime_credible:
            time_map[item.path] = (item.mtime, "mtime")
        else:
            undetermined.append(
                UndeterminedItem(item.path, "缺少可信时间依据：Git 历史不可用，且文件修改时间疑似批量检出")
            )

    reference = collect_reference_counts(
        root,
        [path for path in candidates if path in time_map],
        files,
        reader=text_reader,
    )
    if not reference.complete:
        for path in candidates:
            if path in time_map:
                undetermined.append(
                    UndeterminedItem(path, f"引用统计不完整：{reference.unreadable_count} 个文本文件未能读取")
                )
        return ZombieResult(
            tuple(),
            tuple(undetermined),
            tuple(degraded),
            mtime_credible,
            git_used,
            False,
        )

    result: list[ZombieCandidate] = []
    for path, (timestamp, basis) in time_map.items():
        idle_days = compute_idle_days(timestamp, now_ts)
        if idle_days < options.zombie_days:
            continue
        if path in reference.referenced:
            continue
        result.append(
            ZombieCandidate(
                file_path=path,
                basis=basis,
                last_activity=format_activity_date(timestamp),
                idle_days=idle_days,
                reference_count=0,
                risk_level=RiskLevel.SUGGESTION,
                suggestion="确认是否仍被课程使用；若不再使用，移动到 archive/ 或删除（需人工确认）",
            )
        )
    return ZombieResult(
        tuple(sorted(result, key=lambda item: item.file_path)),
        tuple(undetermined),
        tuple(degraded),
        mtime_credible,
        git_used,
        True,
    )
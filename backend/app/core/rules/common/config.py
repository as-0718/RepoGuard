from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .models import IssueLevel

DEFAULT_BINARY_EXTENSIONS: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".mp3", ".wav", ".flac",
    ".zip", ".rar", ".7z", ".gz", ".tar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".class", ".pyc", ".o", ".a",
)

DEFAULT_DIRECTORY_MAP: dict[str, tuple[str, ...]] = {
    "md": ("docs/",),
    "c": ("lab/", "src/"),
    "h": ("lab/", "src/"),
    "py": ("backend/", "scripts/", "lab/"),
    "png": ("assets/", "docs/assets/"),
    "jpg": ("assets/", "docs/assets/"),
    "jpeg": ("assets/", "docs/assets/"),
    "gif": ("assets/", "docs/assets/"),
    "bmp": ("assets/", "docs/assets/"),
    "webp": ("assets/", "docs/assets/"),
    "svg": ("assets/", "docs/assets/"),
    "ico": ("assets/", "docs/assets/"),
}

DEFAULT_PLACEHOLDER_WORDS: tuple[str, ...] = (
    "示例", "占位", "demo", "example", "sample", "mock", "xxxx",
)


@dataclass(frozen=True, slots=True)
class PatternSpec:
    rule_id: str
    pattern: re.Pattern[str]
    level: IssueLevel
    message: str
    suggestion: str
    language: str = "any"
    exemptable: bool = True


@dataclass(frozen=True, slots=True)
class RuleConfig:
    large_file_warn_mb: float = 1.0
    large_file_fail_mb: float = 5.0
    code_scan_max_mb: float = 5.0
    large_text_scan_timeout_s: float = 1.0
    per_file_budget_ms: int = 300
    link_max_per_file: int = 200
    max_findings_per_rule_per_file: int = 5
    directory_map: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType(dict(DEFAULT_DIRECTORY_MAP))
    )
    hard_dangerous_patterns: tuple[PatternSpec, ...] = ()
    suspicious_patterns: tuple[PatternSpec, ...] = ()
    secret_patterns: tuple[PatternSpec, ...] = ()
    placeholder_context_words: tuple[str, ...] = DEFAULT_PLACEHOLDER_WORDS
    binary_extensions: tuple[str, ...] = DEFAULT_BINARY_EXTENSIONS
    naming_chinese_mode: str = "仅建议"
    output_language: str = "zh-CN"


@dataclass(frozen=True, slots=True)
class ConfigBuildResult:
    config: RuleConfig
    warnings: tuple[str, ...] = ()


def _spec(
    rule_id: str,
    pattern: str,
    level: IssueLevel,
    message: str,
    suggestion: str,
    language: str = "any",
    exemptable: bool = True,
    flags: int = 0,
) -> PatternSpec:
    return PatternSpec(
        rule_id=rule_id,
        pattern=re.compile(pattern, flags),
        level=level,
        message=message,
        suggestion=suggestion,
        language=language,
        exemptable=exemptable,
    )


def _default_hard_patterns() -> tuple[PatternSpec, ...]:
    return (
        _spec("code-004", r"(?<![A-Za-z0-9_])gets\s*\(", IssueLevel.MUST_FIX,
              "使用了不检查边界的 gets 函数，存在缓冲区溢出风险",
              "改用 fgets(buf, sizeof(buf), stdin) 读取输入", "c"),
        _spec("code-004", r"(?<![A-Za-z0-9_])strcpy\s*\(", IssueLevel.MUST_FIX,
              "使用了不检查长度的 strcpy 函数，存在缓冲区溢出风险",
              "改用 snprintf 或 strncpy 并手动补上字符串结束符", "c"),
        _spec("code-004", r"(?<![A-Za-z0-9_])strcat\s*\(", IssueLevel.MUST_FIX,
              "使用了不检查长度的 strcat 函数，存在缓冲区溢出风险",
              "改用 strncat 并限制拼接长度", "c"),
        _spec("code-004", r"(?<![A-Za-z0-9_])sprintf\s*\(", IssueLevel.MUST_FIX,
              "使用了不限制输出长度的 sprintf 函数，存在溢出风险",
              "改用 snprintf(buf, sizeof(buf), ...) 格式化输出", "c"),
        _spec("code-004", r"(?<![A-Za-z0-9_])scanf\s*\(\s*\"%s\"", IssueLevel.MUST_FIX,
              "scanf 使用无宽度限制的 %s，输入过长会溢出缓冲区",
              "改用 scanf(\"%99s\", buf) 并明确缓冲区大小", "c"),
        _spec("code-005", r"(?<![A-Za-z0-9_.])(?:eval|exec)\s*\(", IssueLevel.MUST_FIX,
              "使用了 eval 或 exec，可能执行不受信任的任意代码",
              "改用 ast.literal_eval 或显式白名单映射", "python"),
        _spec("code-006", r"\bos\.(?:system|popen)\s*\(\s*(?:f[\"']|[^)\n]*\+|[^)\n]*%|[^)\n]*\.format)",
              IssueLevel.MUST_FIX,
              "使用字符串拼接结果调用系统命令，存在命令注入风险",
              "改用 subprocess.run([...], shell=False)，必要时用 shlex.quote", "python"),
        _spec("code-006", r"\bsubprocess\.\w+\s*\([^)\n]*shell\s*=\s*True",
              IssueLevel.MUST_FIX,
              "subprocess 以 shell=True 执行拼接命令，存在命令注入风险",
              "改用 subprocess.run([...], shell=False) 传参数列表", "python"),
    )


def _default_suspicious_patterns() -> tuple[PatternSpec, ...]:
    return (
        _spec("code-007", r"\bwhile\s*\(\s*(?:1|true|TRUE)\s*\)", IssueLevel.SUGGESTION,
              "使用了 while(1) 形式的死循环，可读性较差",
              "改用明确的退出条件变量，或注明退出方式；嵌入式轮询场景可保留", "c"),
        _spec("code-007", r"\bfor\s*\(\s*;\s*;\s*\)", IssueLevel.SUGGESTION,
              "使用了 for(;;) 形式的死循环，可读性较差",
              "改用明确的退出条件变量，或注明退出方式", "c"),
        _spec("code-007", r"\bos\.system\s*\(", IssueLevel.SUGGESTION,
              "使用了 os.system 执行系统命令，建议关注命令注入风险",
              "改用 subprocess.run 传入参数列表，并避免 shell=True", "python"),
        _spec("code-007", r"\bsubprocess\.", IssueLevel.SUGGESTION,
              "使用了 subprocess 调用外部命令，请确认命令参数来源可信",
              "优先传入参数列表，避免 shell=True 与字符串拼接", "python"),
        _spec("code-007", r"\bexcept\s*:", IssueLevel.SUGGESTION,
              "使用了裸 except，会吞掉所有异常导致难以排查",
              "改为 except Exception as exc: 并记录具体异常信息", "python"),
    )


def _default_secret_patterns() -> tuple[PatternSpec, ...]:
    return (
        _spec("sens-003", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
              IssueLevel.MUST_FIX,
              "检测到 PEM 私钥内容，属于高危敏感信息",
              "立即移除私钥并轮换凭据，改用环境变量或密钥管理服务",
              "any", exemptable=False),
        _spec("sens-004", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", IssueLevel.MUST_FIX,
              "检测到疑似 AWS 访问密钥，属于高危敏感信息",
              "立即移除并轮换密钥，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{10,}\b",
              IssueLevel.MUST_FIX,
              "检测到疑似 GitHub 令牌，属于高危敏感信息",
              "立即移除并轮换令牌，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\bgithub_pat_[A-Za-z0-9_]{10,}", IssueLevel.MUST_FIX,
              "检测到疑似 GitHub 细粒度令牌，属于高危敏感信息",
              "立即移除并轮换令牌，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\bglpat-[A-Za-z0-9_-]{10,}", IssueLevel.MUST_FIX,
              "检测到疑似 GitLab 访问令牌，属于高危敏感信息",
              "立即移除并轮换令牌，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\bxox[baprs]-[A-Za-z0-9-]{10,}", IssueLevel.MUST_FIX,
              "检测到疑似 Slack 令牌，属于高危敏感信息",
              "立即移除并轮换令牌，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\bsk-[A-Za-z0-9]{20,}", IssueLevel.MUST_FIX,
              "检测到疑似 API 密钥，属于高危敏感信息",
              "立即移除并轮换密钥，改用环境变量或配置模板占位"),
        _spec("sens-004", r"\bAIza[0-9A-Za-z_-]{35}\b", IssueLevel.MUST_FIX,
              "检测到疑似 Google API 密钥，属于高危敏感信息",
              "立即移除并轮换密钥，改用环境变量或配置模板占位"),
        _spec("sens-005",
              r"(?i)\b(?:password|passwd|pwd|token|secret|api_key|apikey|access_key)\b\s*[:=]\s*[\"'][^\"'\n]{1,}[\"']",
              IssueLevel.MUST_FIX,
              "检测到疑似明文口令或令牌赋值，属于敏感信息",
              "改用环境变量读取或配置模板占位，不要提交真实口令"),
        _spec("sens-005", r"(?i)\b[a-z][a-z0-9+.-]*://[^:/\s]+:[^@\s]+@[^/\s]+",
              IssueLevel.MUST_FIX,
              "检测到包含账号口令的数据库连接串，属于敏感信息",
              "改从环境变量读取连接信息，并将口令替换为占位符", "any", exemptable=False),
        _spec("sens-006", r"\b[0-9a-fA-F]{32,}\b", IssueLevel.SUGGESTION,
              "检测到较长十六进制字符串，可能为密钥或令牌",
              "若为示例请标注占位说明；若为真实凭据请立即移除并轮换"),
    )


DEFAULT_HARD_PATTERNS = _default_hard_patterns()
DEFAULT_SUSPICIOUS_PATTERNS = _default_suspicious_patterns()
DEFAULT_SECRET_PATTERNS = _default_secret_patterns()

DEFAULT_CONFIG = RuleConfig(
    hard_dangerous_patterns=DEFAULT_HARD_PATTERNS,
    suspicious_patterns=DEFAULT_SUSPICIOUS_PATTERNS,
    secret_patterns=DEFAULT_SECRET_PATTERNS,
)


def default_config() -> RuleConfig:
    return DEFAULT_CONFIG


def _copy_directory_map(value: Mapping[str, tuple[str, ...]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({str(key).lower(): tuple(str(item) for item in items) for key, items in value.items()})


def config_from_mapping(
    data: Mapping[str, object],
    base: RuleConfig | None = None,
) -> ConfigBuildResult:
    current = base or DEFAULT_CONFIG
    warnings: list[str] = []
    updates: dict[str, object] = {}

    float_fields = (
        "large_file_warn_mb", "large_file_fail_mb", "code_scan_max_mb",
        "large_text_scan_timeout_s",
    )
    int_fields = ("per_file_budget_ms", "link_max_per_file", "max_findings_per_rule_per_file")

    for name in float_fields:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            warnings.append(f"配置项 {name} 取值非法，已使用默认值")
            continue
        updates[name] = float(value)

    for name in int_fields:
        if name not in data:
            continue
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            warnings.append(f"配置项 {name} 取值非法，已使用默认值")
            continue
        updates[name] = value

    warn = float(updates.get("large_file_warn_mb", current.large_file_warn_mb))
    fail = float(updates.get("large_file_fail_mb", current.large_file_fail_mb))
    if warn >= fail:
        updates.pop("large_file_warn_mb", None)
        updates.pop("large_file_fail_mb", None)
        warnings.append("配置项 large_file_warn_mb 与 large_file_fail_mb 阈值倒置，已使用默认值")

    if "directory_map" in data:
        raw_map = data["directory_map"]
        if not isinstance(raw_map, Mapping):
            warnings.append("配置项 directory_map 取值非法，已使用默认值")
        else:
            normalized: dict[str, tuple[str, ...]] = {}
            valid = True
            for key, value in raw_map.items():
                if not isinstance(key, str) or not isinstance(value, (list, tuple)):
                    valid = False
                    break
                normalized[key.lstrip(".").lower()] = tuple(str(item) for item in value)
            if not valid or not all(key in normalized for key in ("md", "c", "h", "py")):
                warnings.append("配置项 directory_map 缺少必需项（.md/.c/.h/.py），已使用默认值")
            else:
                updates["directory_map"] = MappingProxyType(normalized)

    if "placeholder_context_words" in data:
        words = data["placeholder_context_words"]
        if isinstance(words, (list, tuple)) and all(isinstance(item, str) for item in words):
            updates["placeholder_context_words"] = tuple(words)
        else:
            warnings.append("配置项 placeholder_context_words 取值非法，已使用默认值")

    if "binary_extensions" in data:
        extensions = data["binary_extensions"]
        if isinstance(extensions, (list, tuple)) and all(isinstance(item, str) for item in extensions):
            updates["binary_extensions"] = tuple(
                item if item.startswith(".") else f".{item}" for item in extensions
            )
        else:
            warnings.append("配置项 binary_extensions 取值非法，已使用默认值")

    for fixed_name, fixed_value in (("naming_chinese_mode", "仅建议"), ("output_language", "zh-CN")):
        if fixed_name in data and data[fixed_name] != fixed_value:
            warnings.append(f"配置项 {fixed_name} 为固定值，已使用默认值")

    for pattern_name, defaults in (
        ("hard_dangerous_patterns", current.hard_dangerous_patterns),
        ("secret_patterns", current.secret_patterns),
    ):
        if pattern_name not in data:
            continue
        extras = data[pattern_name]
        if not isinstance(extras, (list, tuple)):
            warnings.append(f"配置项 {pattern_name} 取值非法，已忽略")
            continue
        appended: list[PatternSpec] = []
        for item in extras:
            if not isinstance(item, Mapping):
                warnings.append(f"配置项 {pattern_name} 中存在非法项，已忽略")
                continue
            try:
                level = IssueLevel(str(item.get("level", "优化建议")))
                appended.append(
                    _spec(
                        str(item["rule_id"]),
                        str(item["pattern"]),
                        level,
                        str(item["message"]),
                        str(item["suggestion"]),
                        str(item.get("language", "any")),
                        bool(item.get("exemptable", True)),
                    )
                )
            except (KeyError, ValueError, re.error):
                warnings.append(f"配置项 {pattern_name} 中存在非法项，已忽略")
        updates[pattern_name] = defaults + tuple(appended)

    try:
        merged = replace(current, **updates)
    except (TypeError, ValueError):
        warnings.append("配置合并失败，已使用默认配置")
        merged = DEFAULT_CONFIG
    return ConfigBuildResult(config=merged, warnings=tuple(warnings))


def load_config_file(
    path: str | Path,
    base: RuleConfig | None = None,
) -> ConfigBuildResult:
    current = base or DEFAULT_CONFIG
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return ConfigBuildResult(
            config=current,
            warnings=(f"无法读取配置文件：{path}，已使用默认配置",),
        )
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ConfigBuildResult(
            config=current,
            warnings=(f"配置文件不是合法 JSON：{path}，已使用默认配置",),
        )
    if not isinstance(data, Mapping):
        return ConfigBuildResult(
            config=current,
            warnings=(f"配置文件内容不是 JSON 对象：{path}，已使用默认配置",),
        )
    return config_from_mapping(data, base=current)


def build_config(
    *,
    overrides: Mapping[str, object] | None = None,
    config_file: str | Path | None = None,
) -> ConfigBuildResult:
    result = ConfigBuildResult(config=DEFAULT_CONFIG, warnings=())
    if config_file is not None:
        file_result = load_config_file(config_file, base=result.config)
        result = ConfigBuildResult(
            config=file_result.config,
            warnings=result.warnings + file_result.warnings,
        )
    if overrides:
        override_result = config_from_mapping(overrides, base=result.config)
        result = ConfigBuildResult(
            config=override_result.config,
            warnings=result.warnings + override_result.warnings,
        )
    return result
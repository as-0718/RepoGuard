from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass

from .models import WebhookError
from .settings import WebhookConfig

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class SignatureError(WebhookError):
    pass


@dataclass(frozen=True, slots=True)
class SignatureResult:
    ok: bool
    used_previous: bool
    timestamp_seconds: int
    skew_seconds: int
    timestamp_unit: str


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def build_signature(secret: str, timestamp_header_value: str, raw_body: bytes) -> str:
    payload = timestamp_header_value.strip().encode("utf-8") + b"." + raw_body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def parse_signature_header(value: str | None, prefix: str) -> str:
    if value is None or not value.strip():
        raise SignatureError("WEBHOOK_SIGNATURE_MISSING", 401, "缺少 Webhook 签名")
    text = value.strip()
    if prefix and not text.startswith(prefix):
        raise SignatureError("WEBHOOK_SIGNATURE_INVALID", 401, "Webhook 签名无效")
    if prefix:
        text = text[len(prefix):]
    normalized = text.strip().lower()
    if len(normalized) != 64 or not re.match(r"^[0-9a-f]{64}$", normalized):
        raise SignatureError("WEBHOOK_SIGNATURE_INVALID", 401, "Webhook 签名无效")
    return normalized


def parse_timestamp(
    value: str | None, now: float, window_seconds: int
) -> tuple[int, int, str]:
    if value is None or not value.strip():
        raise SignatureError("WEBHOOK_TIMESTAMP_MISSING", 401, "缺少 Webhook 时间戳")
    text = value.strip()
    if not text.isdigit() or len(text) not in (10, 13):
        raise SignatureError("WEBHOOK_TIMESTAMP_INVALID", 401, "Webhook 时间戳格式不合法")
    unit = "seconds" if len(text) == 10 else "milliseconds"
    seconds = int(text) if unit == "seconds" else int(text) // 1000
    skew = int(now) - seconds
    if abs(skew) > window_seconds:
        code = "WEBHOOK_TIMESTAMP_INVALID" if seconds > now else "WEBHOOK_TIMESTAMP_EXPIRED"
        raise SignatureError(code, 401, "Webhook 时间戳已过期" if seconds <= now else "Webhook 时间戳不合法")
    return seconds, skew, unit


def secret_configured(config: WebhookConfig) -> bool:
    value = config.secret.strip()
    return bool(value) and not has_control_chars(value)


def has_control_chars(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def verify_signature(
    headers: Mapping[str, str],
    raw_body: bytes,
    config: WebhookConfig,
    now: float | None = None,
) -> SignatureResult:
    if not secret_configured(config):
        raise SignatureError("WEBHOOK_SECRET_NOT_CONFIGURED", 503, "Webhook 签名密钥未配置")
    signature_value = _header(headers, config.signature_header)
    if signature_value is None or not signature_value.strip():
        raise SignatureError("WEBHOOK_SIGNATURE_MISSING", 401, "缺少 Webhook 签名")
    timestamp_value = _header(headers, config.timestamp_header)
    if timestamp_value is None or not timestamp_value.strip():
        raise SignatureError("WEBHOOK_TIMESTAMP_MISSING", 401, "缺少 Webhook 时间戳")
    current = time.time() if now is None else now
    timestamp_seconds, skew, unit = parse_timestamp(
        timestamp_value, current, config.replay_window_seconds
    )
    provided = parse_signature_header(signature_value, config.signature_prefix)
    expected = build_signature(config.secret, timestamp_value.strip(), raw_body)
    if hmac.compare_digest(expected, provided):
        return SignatureResult(True, False, timestamp_seconds, skew, unit)
    if config.secret_previous.strip():
        previous = build_signature(config.secret_previous, timestamp_value.strip(), raw_body)
        if hmac.compare_digest(previous, provided):
            return SignatureResult(True, True, timestamp_seconds, skew, unit)
    raise SignatureError("WEBHOOK_SIGNATURE_INVALID", 401, "Webhook 签名无效")
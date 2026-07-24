"""Secret redaction for anything Orkestra persists or exports.

Applied to event payload text, per-task logs, reports, and support
bundles. Patterns favor recall over precision: a redacted false positive
is annoying; a leaked credential is a disaster.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    # Anthropic / OpenAI / generic sk- keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    # Anthropic admin/oauth style
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"),
    # GitHub tokens (classic and fine-grained)
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Google API keys
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    # AWS access key id + secret
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\baws_secret_access_key\b\s*[=:]\s*\S+"),
    # Slack tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
    # Bearer headers
    re.compile(r"(?i)\bauthorization\s*[=:]\s*bearer\s+\S+"),
    # PEM blocks
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    # Generic credential assignments: password=..., api_key: ..., token=...
    re.compile(
        r"""(?ix)
        \b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|
           client[_-]?secret|private[_-]?key|session[_-]?token)\b
        \s*[=:]\s*
        (?!\[REDACTED\])["']?[^\s"']{6,}["']?
        """,
    ),
]


def redact(text: str) -> str:
    """Return *text* with credential-shaped substrings replaced."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_mapping(env: dict[str, str]) -> dict[str, str]:
    """Redact values of sensitive-looking keys in a mapping (for reports)."""
    sensitive = re.compile(r"(?i)(key|token|secret|password|credential|auth)")
    return {k: (REDACTED if sensitive.search(k) else v) for k, v in env.items()}

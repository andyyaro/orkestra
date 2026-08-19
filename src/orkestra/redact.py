"""Secret redaction for anything Orkestra persists or exports.

Applied to event payload text, per-task logs, reports, and support
bundles. Patterns favor recall over precision: a redacted false positive
is annoying; a leaked credential is a disaster. The v0.1.1 revision
implements the improvements identified by Orkestra's own dogfood review
(docs/development/SELF_REVIEW.md): provider-prefixed and quoted-JSON
credential keys, URL userinfo, cloud/platform token formats, structured
pre-serialization redaction, and reduced false positives on benign
status values.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

#: (pattern, replacement) pairs applied in order. Most replace the whole
#: match; URL userinfo keeps the non-secret parts via groups.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Anthropic / OpenAI / generic sk- keys
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), REDACTED),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}\b"), REDACTED),
    # GitHub tokens (classic and fine-grained)
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), REDACTED),
    # GitLab PATs and CI job tokens
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{10,}\b"), REDACTED),
    (re.compile(r"\bglcbt-[A-Za-z0-9_-]{10,}\b"), REDACTED),
    # Google API keys
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), REDACTED),
    # GCP service-account key material in JSON responses
    (
        re.compile(r'(?i)(["\']?privateKeyData["\']?\s*[=:]\s*)["\']?[A-Za-z0-9+/=_-]{8,}["\']?'),
        r"\1" + REDACTED,
    ),
    # AWS access key id + secret + session token
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"(?i)\baws_secret_access_key\b\s*[=:]\s*\S+"), REDACTED),
    (re.compile(r"(?i)\baws_session_token\b\s*[=:]\s*\S+"), REDACTED),
    # Azure storage connection-string fields and SAS signatures
    (re.compile(r"(?i)\b(AccountKey|SharedAccessSignature)\s*=\s*[^;\s\"']+"), REDACTED),
    (re.compile(r"(?i)([?&]sig=)[^&\s\"']+"), r"\1" + REDACTED),
    # Slack tokens (bot/user/app-level)
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), REDACTED),
    (re.compile(r"\bxapp-[A-Za-z0-9-]{10,}\b"), REDACTED),
    # npm tokens (modern npm_ prefix and .npmrc _authToken lines)
    (re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"), REDACTED),
    (re.compile(r"(?i)(_authToken\s*=\s*)\S+"), r"\1" + REDACTED),
    # PyPI API tokens
    (re.compile(r"\bpypi-[A-Za-z0-9_-]{8,}\b"), REDACTED),
    # JWTs
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"), REDACTED),
    # Bearer headers, raw and JSON-serialized
    (re.compile(r"(?i)\bauthorization\b[\"']?\s*[=:]\s*[\"']?bearer\s+[^\s\"']+"), REDACTED),
    # URL userinfo passwords: scheme://user:secret@host - keep user and host
    (re.compile(r"(://[^/\s:@\"']+:)[^@\s\"']+(@)"), r"\1" + REDACTED + r"\2"),
    # PEM blocks
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
    # Generic credential assignments. Key side: any name ENDING in a
    # sensitive word (covers AWS_SESSION_TOKEN, GITLAB_TOKEN, plain token=,
    # DATABASE_PASSWORD, camelCase apiKey), optionally JSON-quoted.
    # Value side: stops at commas/semicolons (no over-consumption) and a
    # negative lookahead skips obvious non-secrets: template placeholders,
    # absolute paths, and common status words.
    (
        re.compile(
            r"""(?ix)
        (?<![A-Za-z0-9])
        ["']?
        [A-Za-z0-9_.-]*?
        (?:password|passwd|secret|api[_-]?key|apikey|token|credential|
           private[_-]?key)
        ["']?
        \s*[=:]\s*
        (?!\[REDACTED\])
        (?!["']?(?:\$\{|\$\(|%\())                 # ${VAR} $(cmd) %(tpl)
        (?!["']?/)                                  # absolute paths
        (?!["']?(?:missing|configured|disabled|enabled|unset|none|null|
                 true|false|redacted|placeholder|changeme|example|
                 xxx+|\*{3,})["']?(?:[\s,;]|$))    # status words / masks
        ["']?[^\s"',;]{6,}["']?
        """,
        ),
        REDACTED,
    ),
]

#: Mapping keys whose values are always redacted in structured data.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:^|[_.-])(?:password|passwd|secret|api[_-]?key|apikey|token|"
    r"credential|authorization|auth|private[_-]?key|privatekeydata|"
    r"accountkey|signature|key)$|^(?:key|auth)"
)


def redact(text: str) -> str:
    """Return *text* with credential-shaped substrings replaced."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(env: dict[str, str]) -> dict[str, str]:
    """Redact values of sensitive-looking keys in a flat mapping (reports)."""
    sensitive = re.compile(r"(?i)(key|token|secret|password|credential|auth)")
    return {k: (REDACTED if sensitive.search(k) else v) for k, v in env.items()}


def redact_structure(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact structured data BEFORE serialization.

    Values under sensitive keys are replaced wholesale; all string leaves
    additionally pass through :func:`redact`. Closes the quoted-JSON-key
    gaps that text-level patterns cannot reliably cover (dogfood finding 1).
    """
    if _depth > 20:  # defensive: agent output may be adversarial
        return REDACTED
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key):
                result[key] = REDACTED
            else:
                result[key] = redact_structure(item, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        return [redact_structure(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value

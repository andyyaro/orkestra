"""Defensive JSON/JSONL helpers for adapter parsers.

Agent CLIs interleave banners, warnings, and truncated lines with JSON.
Nothing here raises on garbage; unparseable input becomes RAW events or
is retained for text-level fallbacks.
"""

from __future__ import annotations

import json
import re
from typing import Any


def try_parse_json(line: str) -> dict[str, Any] | None:
    """Parse a line as a JSON object; None for anything else."""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of one JSON object from free text.

    Used for agents without schema-constrained output (Antigravity,
    Gemini): tries the whole text, then fenced blocks, then the first
    balanced ``{...}`` region.
    """
    candidates: list[str] = [text.strip()]
    candidates.extend(m.group(1).strip() for m in _FENCE_RE.finditer(text))
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(brace_start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[brace_start : i + 1])
                        break
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None

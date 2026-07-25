"""Provider-neutral reasoning-effort model.

One vocabulary for users — ``auto | low | medium | high | max`` — with
an explicit, per-adapter mapping to each CLI's real control surface.
Unsupported combinations are rejected with a plain-language explanation
at configuration time; effort is **never** silently ignored.

``auto`` always means "the adapter's own default" and is valid
everywhere (it emits no flag).
"""

from __future__ import annotations

from dataclasses import dataclass

EFFORT_LEVELS = ("auto", "low", "medium", "high", "max")


@dataclass(frozen=True)
class EffortSupport:
    """What one adapter can do, and how to say it in its CLI dialect."""

    #: neutral level -> CLI value (levels absent here are unsupported;
    #: "auto" is implicitly supported everywhere and emits nothing).
    mapping: dict[str, str]
    #: plain-language note used in rejection messages.
    note: str

    def supported_levels(self) -> list[str]:
        return ["auto", *self.mapping.keys()]

    def cli_value(self, level: str) -> str | None:
        """CLI value for a neutral level; None for 'auto' (omit the flag)."""
        if level == "auto":
            return None
        return self.mapping[level]


#: The authoritative table. Sources: agy --help (low|medium|high,
#: verified live 2026-07-24); Codex config `model_reasoning_effort`
#: accepts minimal|low|medium|high per its config reference — "max" has
#: no real counterpart on either, so it maps only where a top tier
#: genuinely exists.
ADAPTER_EFFORT: dict[str, EffortSupport] = {
    "antigravity-cli": EffortSupport(
        mapping={"low": "low", "medium": "medium", "high": "high"},
        note="the Antigravity CLI exposes --effort low|medium|high; there is no 'max' tier",
    ),
    "codex-cli": EffortSupport(
        mapping={"low": "low", "medium": "medium", "high": "high"},
        note=(
            "Codex exposes model_reasoning_effort low|medium|high; there is "
            "no 'max' tier — 'high' is its top setting"
        ),
    ),
    "claude-code": EffortSupport(
        mapping={},
        note=(
            "Claude Code has no effort control — pick a model tier instead "
            "(e.g. `orkestra agents set <name> --model haiku|sonnet|opus`)"
        ),
    ),
    "gemini-cli": EffortSupport(
        mapping={},
        note=(
            "the Gemini CLI has no effort control — model variants encode it "
            "(e.g. --model flash vs pro)"
        ),
    ),
    "fake": EffortSupport(
        mapping={"low": "low", "medium": "medium", "high": "high", "max": "max"},
        note="the fake adapter accepts every level (it records, never reasons)",
    ),
    "external": EffortSupport(
        mapping={"low": "low", "medium": "medium", "high": "high", "max": "max"},
        note=(
            "external agents receive the effort level in the task brief and "
            "decide themselves what it means"
        ),
    ),
}


def validate_effort(adapter: str, effort: str | None) -> str | None:
    """Return a plain-language error when *effort* is unsupported, else None."""
    if effort is None or effort == "auto":
        return None
    if effort not in EFFORT_LEVELS:
        return f"effort {effort!r} is not a valid level — use one of: " + " | ".join(EFFORT_LEVELS)
    support = ADAPTER_EFFORT.get(adapter)
    if support is None:
        return None  # unknown adapter slugs fail elsewhere (registry)
    if effort not in support.mapping:
        supported = " | ".join(support.supported_levels())
        return (
            f"effort {effort!r} is not supported by the {adapter} adapter: "
            f"{support.note}. Supported here: {supported}."
        )
    return None

"""Quality/speed presets and profile generation.

Presets adjust model profiles, effort, probe behavior, concurrency, and
budgets. They **never** touch deterministic verification or independent
review — those are not preferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentProfile:
    name: str
    adapter: str
    model: str | None = None
    effort: str | None = None
    token_budget: int | None = None


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    description: str
    max_concurrency: int
    probes_mode: str
    probes_budget: int
    #: adapter id -> list of profiles to create for it (multi-profile capable)
    profiles: dict[str, list[AgentProfile]] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    "faster": Preset(
        key="faster",
        label="Faster",
        description="cheapest tiers, no probes — quick iterations, lighter results",
        max_concurrency=2,
        probes_mode="off",
        probes_budget=0,
        profiles={
            "claude-code": [AgentProfile("claude", "claude-code", model="haiku")],
            "codex-cli": [AgentProfile("codex", "codex-cli", effort="low")],
            "antigravity-cli": [AgentProfile("antigravity", "antigravity-cli", effort="low")],
        },
    ),
    "balanced": Preset(
        key="balanced",
        label="Balanced (recommended)",
        description="adapter-default models, cached probes — the sensible middle",
        max_concurrency=2,
        probes_mode="cached",
        probes_budget=6,
        profiles={
            "claude-code": [AgentProfile("claude", "claude-code")],
            "codex-cli": [AgentProfile("codex", "codex-cli")],
            "antigravity-cli": [AgentProfile("antigravity", "antigravity-cli")],
        },
    ),
    "max-quality": Preset(
        key="max-quality",
        label="Maximum quality",
        description=(
            "top tiers + a second fast Claude profile for breadth; live "
            "probes — slower and hungrier on your plan limits"
        ),
        max_concurrency=3,
        probes_mode="live",
        probes_budget=8,
        profiles={
            "claude-code": [
                AgentProfile("claude-deep", "claude-code", model="opus"),
                AgentProfile("claude-fast", "claude-code", model="haiku"),
            ],
            "codex-cli": [AgentProfile("codex", "codex-cli", effort="high")],
            "antigravity-cli": [AgentProfile("antigravity", "antigravity-cli", effort="high")],
        },
    ),
}


def profiles_for(preset: Preset, available_adapters: list[str]) -> list[AgentProfile]:
    """Profiles the preset creates for the adapters actually available."""
    result: list[AgentProfile] = []
    for adapter_id in available_adapters:
        result.extend(preset.profiles.get(adapter_id, []))
    return result


def pick_director(profiles: list[AgentProfile]) -> str:
    """Claude-family profile if present (deepest first), else the first."""
    claude_profiles = [p for p in profiles if p.adapter == "claude-code"]
    if claude_profiles:
        return claude_profiles[0].name
    return profiles[0].name

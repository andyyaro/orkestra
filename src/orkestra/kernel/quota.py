"""Quota-aware agent selection.

Two deterministic signals drive scheduling decisions:

1. **Token budgets** (``agents.<name>.token_budget``, per run): once an
   agent's recorded input+output tokens for the run exceed its budget,
   it is excluded from new dispatches (existing in-flight work finishes).
2. **Rate-limit cooldowns**: a rate-limited agent enters a per-agent
   exponential cooldown. The scheduler prefers available alternatives
   immediately instead of sleeping; it only waits when every eligible
   agent is cooling down.

Both are advisory *inputs* the kernel computes from its own ledger —
never from agent claims (evidence over self-report).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orkestra.schemas.config import ProjectConfig
    from orkestra.store import Store


@dataclass
class QuotaTracker:
    """Per-run quota state owned by the orchestrator."""

    config: ProjectConfig
    store: Store
    run_id: str
    cooldown_base_s: float = 60.0
    cooldown_factor: float = 2.0
    cooldown_max_s: float = 900.0
    _cooldown_until: dict[str, float] = field(default_factory=dict)
    _consecutive_limits: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------ budgets

    def tokens_used(self, agent: str) -> int:
        rows = self.store.usage_summary(self.run_id)
        for row in rows:
            if row["agent"] == agent:
                return int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0)
        return 0

    def budget_exhausted(self, agent: str) -> bool:
        agent_config = self.config.agents.get(agent)
        if agent_config is None or agent_config.token_budget is None:
            return False
        return self.tokens_used(agent) >= agent_config.token_budget

    # ---------------------------------------------------------- cooldowns

    def note_rate_limit(self, agent: str) -> float:
        """Record a rate-limit signal; returns the applied cooldown seconds."""
        strikes = self._consecutive_limits.get(agent, 0)
        delay = min(
            self.cooldown_base_s * (self.cooldown_factor**strikes),
            self.cooldown_max_s,
        )
        self._consecutive_limits[agent] = strikes + 1
        self._cooldown_until[agent] = time.monotonic() + delay
        return delay

    def note_success(self, agent: str) -> None:
        self._consecutive_limits.pop(agent, None)
        self._cooldown_until.pop(agent, None)

    def cooling_down(self, agent: str) -> bool:
        deadline = self._cooldown_until.get(agent)
        return deadline is not None and time.monotonic() < deadline

    def cooldown_remaining(self, agent: str) -> float:
        deadline = self._cooldown_until.get(agent)
        if deadline is None:
            return 0.0
        return max(0.0, deadline - time.monotonic())

    # ---------------------------------------------------------- selection

    def eligible(self, agent: str) -> bool:
        """Dispatchable right now: within budget and not cooling down."""
        return not self.budget_exhausted(agent) and not self.cooling_down(agent)

    def pick(
        self, failed_agents: list[str], primary: str, fallbacks: list[str]
    ) -> tuple[str | None, float]:
        """Choose the next agent for an attempt.

        Returns ``(agent, wait_s)``: an immediately eligible agent with
        ``wait_s == 0``; a cooling-down agent with the seconds to wait
        before dispatching it; or ``(None, 0)`` when every candidate has
        hard-failed or exhausted its budget.
        """
        chain = [primary, *[f for f in fallbacks if f != primary]]
        candidates = [
            agent
            for agent in chain
            if agent not in failed_agents and not self.budget_exhausted(agent)
        ]
        if not candidates:
            return None, 0.0
        for agent in candidates:
            if not self.cooling_down(agent):
                return agent, 0.0
        soonest = min(candidates, key=self.cooldown_remaining)
        return soonest, self.cooldown_remaining(soonest)

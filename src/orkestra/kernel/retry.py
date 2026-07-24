"""Bounded retry and backoff policy (no infinite loops, rule 1.2)."""

from __future__ import annotations

from dataclasses import dataclass

from orkestra.schemas.agent import ErrorKind

#: Error kinds where retrying the same agent may help.
RETRYABLE: frozenset[ErrorKind] = frozenset(
    {ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT, ErrorKind.CRASH, ErrorKind.INVALID_OUTPUT,
     ErrorKind.UNKNOWN}
)

#: Error kinds where the agent is unusable and a fallback should be tried.
FALLBACK_IMMEDIATELY: frozenset[ErrorKind] = frozenset(
    {ErrorKind.AUTH, ErrorKind.UNAVAILABLE}
)


@dataclass(frozen=True)
class BackoffPolicy:
    base_s: float = 5.0
    factor: float = 2.0
    max_s: float = 300.0
    rate_limit_base_s: float = 60.0

    def delay(self, attempt_index: int, error: ErrorKind) -> float:
        """Delay before retry *attempt_index* (0-based) for *error*."""
        base = self.rate_limit_base_s if error is ErrorKind.RATE_LIMIT else self.base_s
        return min(base * (self.factor**attempt_index), self.max_s)


def next_agent(
    failed_agents: list[str], primary: str, fallbacks: list[str]
) -> str | None:
    """Pick the next agent to try: primary first, then fallbacks in order.

    Returns None when everyone in the chain has been consumed.
    """
    chain = [primary, *[f for f in fallbacks if f != primary]]
    for candidate in chain:
        if candidate not in failed_agents:
            return candidate
    return None

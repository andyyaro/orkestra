"""Weighted capability matrix built strictly from recorded observations."""

from __future__ import annotations

from collections import defaultdict

from orkestra.schemas.capability import (
    CapabilityMatrix,
    CapabilityObservation,
    CapabilityScore,
)

#: Task outcomes recorded in the ledger feed back as observations with
#: these capability names, so real work continuously reweights the matrix.
TASK_CAPABILITY = {
    "research": "research",
    "plan": "structured_output",
    "implement": "implementation",
    "test": "implementation",
    "review": "bug_detection",
    "debug": "implementation",
    "integrate": "implementation",
    "document": "documentation",
}


def build_matrix(observations: list[CapabilityObservation]) -> CapabilityMatrix:
    """Aggregate observations into evidenced scores with confidence.

    Score: mean of outcomes (objective pass/fail as 1/0, judged scores
    as-is), recency-weighted (later observations weigh more).
    Confidence: n/(n+2) — grows with evidence, never reaches 1.
    """
    grouped: dict[tuple[str, str], list[CapabilityObservation]] = defaultdict(list)
    for obs in observations:
        grouped[(obs.agent, obs.capability)].append(obs)

    matrix = CapabilityMatrix()
    for (agent, capability), group in grouped.items():
        ordered = sorted(group, key=lambda o: o.ts)
        weighted_sum = 0.0
        weight_total = 0.0
        evidence: list[str] = []
        for index, obs in enumerate(ordered):
            value: float | None = None
            if obs.objective_pass is not None:
                value = 1.0 if obs.objective_pass else 0.0
            elif obs.judged_score is not None:
                value = obs.judged_score
            if value is None:
                continue
            weight = 1.0 + index * 0.25  # newer evidence counts more
            weighted_sum += value * weight
            weight_total += weight
            evidence.append(obs.source)
        if weight_total == 0:
            continue
        n = len(evidence)
        matrix.scores.setdefault(agent, {})[capability] = CapabilityScore(
            score=round(weighted_sum / weight_total, 4),
            confidence=round(n / (n + 2), 4),
            evidence=evidence,
        )
    return matrix


def rank_agents(
    matrix: CapabilityMatrix,
    capability: str,
    candidates: list[str],
    *,
    default_score: float = 0.5,
) -> list[str]:
    """Order candidates by evidenced score (unknown agents get the default).

    Ties keep the given candidate order (stable), so configuration order
    is the deterministic tiebreaker.
    """

    def key(agent: str) -> float:
        score = matrix.score_for(agent, capability)
        if score is None:
            return default_score
        # Blend toward the default when confidence is low.
        return score.score * score.confidence + default_score * (1 - score.confidence)

    return sorted(candidates, key=key, reverse=True)

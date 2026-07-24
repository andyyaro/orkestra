"""Deterministic fallback planner.

Used when the director agent is unavailable, lacks the
``structured_director`` feature, exhausts decision retries, or probes
are disabled offline. Produces a valid, conservative plan; assignments
are ranked by the capability matrix with configuration order as the
tiebreaker.
"""

from __future__ import annotations

from orkestra.capabilities.matrix import TASK_CAPABILITY, rank_agents
from orkestra.schemas.capability import CapabilityMatrix
from orkestra.schemas.common import TaskKind
from orkestra.schemas.director import DirectorAnalysis, DirectorPlan, PlannedTask
from orkestra.schemas.task import Assignment, TaskSpec


def heuristic_analysis(spec_text: str) -> DirectorAnalysis:
    lines = [line.strip() for line in spec_text.splitlines() if line.strip()]
    title = next(
        (line.lstrip("# ") for line in lines if line.startswith("#")), "project specification"
    )
    return DirectorAnalysis(
        summary=f"Heuristic analysis of: {title}",
        assumptions=["heuristic planner in use (director agent unavailable or offline)"],
        risks=["plan derived without LLM comprehension; review depth matters more"],
        capability_demands={
            "implementation": 0.9,
            "bug_detection": 0.7,
            "structured_output": 0.5,
            "documentation": 0.3,
        },
    )


def _assign(kind: TaskKind, agents: list[str], matrix: CapabilityMatrix, offset: int) -> Assignment:
    capability = TASK_CAPABILITY.get(kind.value, "implementation")
    ranked = rank_agents(matrix, capability, agents)
    # Rotate by offset so work spreads across agents instead of piling on
    # the single top-ranked one.
    primary = ranked[offset % len(ranked)]
    reviewer_capability = "bug_detection"
    reviewer_ranked = [a for a in rank_agents(matrix, reviewer_capability, agents) if a != primary]
    reviewer = reviewer_ranked[0]
    fallbacks = [a for a in ranked if a not in (primary, reviewer)]
    return Assignment(
        primary=primary,
        reviewers=[reviewer],
        fallbacks=fallbacks or [reviewer],
        rationale=(
            f"heuristic: ranked by evidenced {capability!r} scores, "
            "rotated for load-spread, independent reviewer enforced"
        ),
    )


def heuristic_plan(
    spec_text: str,
    agents: list[str],
    matrix: CapabilityMatrix,
    verify_commands: list[str],
) -> DirectorPlan:
    """Conservative linear plan: implement → test → document."""
    if len(agents) < 2:
        msg = "heuristic planner requires at least two agents"
        raise ValueError(msg)
    tasks = [
        PlannedTask(
            task=TaskSpec(
                key="implement",
                title="Implement the specification",
                kind=TaskKind.IMPLEMENT,
                description=(
                    "Implement the project specification faithfully. "
                    "Work only inside this workspace.\n\nSpecification:\n" + spec_text[:8000]
                ),
                depends_on=[],
                acceptance=verify_commands,
            ),
            assignment=_assign(TaskKind.IMPLEMENT, agents, matrix, 0),
        ),
        PlannedTask(
            task=TaskSpec(
                key="test",
                title="Add or extend tests for the implementation",
                kind=TaskKind.TEST,
                description=(
                    "Add tests covering the implemented behavior, including at "
                    "least one failure-path test. Work only inside this workspace."
                ),
                depends_on=["implement"],
                acceptance=verify_commands,
            ),
            assignment=_assign(TaskKind.TEST, agents, matrix, 1),
        ),
        PlannedTask(
            task=TaskSpec(
                key="document",
                title="Document usage",
                kind=TaskKind.DOCUMENT,
                description=(
                    "Write or update README/usage documentation for what was "
                    "built. Work only inside this workspace."
                ),
                depends_on=["implement"],
                acceptance=[],
            ),
            assignment=_assign(TaskKind.DOCUMENT, agents, matrix, 2),
        ),
    ]
    return DirectorPlan(tasks=tasks, notes="heuristic fallback plan")

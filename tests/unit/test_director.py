"""Unit tests: heuristic planner and kernel-side plan validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.capabilities.matrix import build_matrix
from orkestra.director.heuristic import heuristic_analysis, heuristic_plan
from orkestra.director.service import DirectorService
from orkestra.errors import DirectorError
from orkestra.policy import PolicyEngine
from orkestra.schemas.capability import CapabilityObservation
from orkestra.schemas.common import TaskKind
from orkestra.schemas.config import PolicyConfig
from orkestra.schemas.director import DirectorPlan, PlannedTask
from orkestra.schemas.task import Assignment, TaskSpec

AGENTS = ["claude", "codex", "anti"]


def service(agents: list[str] = AGENTS) -> DirectorService:
    from orkestra.adapters.fake import FakeAdapter

    return DirectorService(
        "claude", FakeAdapter(), PolicyEngine(PolicyConfig(), agents), Path.cwd(),
        offline=True,
    )


class TestHeuristicPlanner:
    def test_plan_valid_for_two_agents(self) -> None:
        plan = heuristic_plan("# Spec\nBuild a thing", ["a", "b"], build_matrix([]),
                              ["pytest -q"])
        assert len(plan.tasks) == 3
        for planned in plan.tasks:
            assert planned.assignment.primary != planned.assignment.reviewers[0]

    def test_plan_valid_for_many_agents(self) -> None:
        agents = [f"agent{i}" for i in range(7)]
        plan = heuristic_plan("# Spec", agents, build_matrix([]), [])
        service(agents).validate_plan(plan, agents)

    def test_plan_spreads_work(self) -> None:
        plan = heuristic_plan("# Spec", AGENTS, build_matrix([]), [])
        primaries = {p.assignment.primary for p in plan.tasks}
        assert len(primaries) >= 2  # not everything on one agent

    def test_matrix_influences_assignment(self) -> None:
        observations = [
            CapabilityObservation(agent="codex", capability="implementation",
                                  source=f"probe:{i}", objective_pass=True)
            for i in range(4)
        ]
        plan = heuristic_plan("# Spec", AGENTS, build_matrix(observations), [])
        implement = next(p for p in plan.tasks if p.task.key == "implement")
        assert implement.assignment.primary == "codex"

    def test_single_agent_rejected(self) -> None:
        with pytest.raises(ValueError, match="two agents"):
            heuristic_plan("# Spec", ["solo"], build_matrix([]), [])

    def test_analysis_mentions_heuristic(self) -> None:
        analysis = heuristic_analysis("# My Project\ndetails")
        assert "My Project" in analysis.summary
        assert analysis.capability_demands


def planned(key: str, primary: str, reviewer: str, deps: list[str] | None = None) -> PlannedTask:
    return PlannedTask(
        task=TaskSpec(key=key, title=key, kind=TaskKind.IMPLEMENT,
                      depends_on=deps or []),
        assignment=Assignment(primary=primary, reviewers=[reviewer]),
    )


class TestPlanValidation:
    def test_valid_plan_passes(self) -> None:
        plan = DirectorPlan(tasks=[planned("a", "claude", "codex"),
                                   planned("b", "codex", "anti", ["a"])])
        service().validate_plan(plan, AGENTS)

    def test_empty_plan_rejected(self) -> None:
        with pytest.raises(DirectorError, match="no tasks"):
            service().validate_plan(DirectorPlan(tasks=[]), AGENTS)

    def test_cycle_rejected(self) -> None:
        plan = DirectorPlan(tasks=[planned("a", "claude", "codex", ["b"]),
                                   planned("b", "codex", "anti", ["a"])])
        with pytest.raises(DirectorError, match="cycle"):
            service().validate_plan(plan, AGENTS)

    def test_self_review_rejected(self) -> None:
        plan = DirectorPlan(tasks=[planned("a", "claude", "claude")])
        with pytest.raises(DirectorError, match="policy"):
            service().validate_plan(plan, AGENTS)

    def test_unknown_agent_rejected(self) -> None:
        plan = DirectorPlan(tasks=[planned("a", "ghost", "codex")])
        with pytest.raises(DirectorError):
            service().validate_plan(plan, AGENTS)

    def test_oversized_plan_rejected(self) -> None:
        tasks = [planned(f"t{i}", "claude", "codex") for i in range(26)]
        with pytest.raises(DirectorError, match="limit"):
            service().validate_plan(DirectorPlan(tasks=tasks), AGENTS)

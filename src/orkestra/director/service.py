"""Director service: structured decision exchanges with bounded retries.

The director is any adapter bound to the role by configuration. Every
exchange sends a prompt plus a JSON schema, validates the structured
response with Pydantic, retries with error feedback up to the configured
bound, and falls back deterministically where a fallback exists.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

from orkestra.adapters.jsonl import extract_json_object
from orkestra.adapters.runner import run_invocation
from orkestra.director import prompts
from orkestra.director.heuristic import heuristic_analysis, heuristic_plan
from orkestra.errors import DirectorError
from orkestra.kernel.dag import TaskDag
from orkestra.schemas.common import TaskKind
from orkestra.schemas.director import (
    DirectorAnalysis,
    DirectorPlan,
    PlanChallenge,
    ReassignmentAdvice,
)
from orkestra.schemas.task import TaskBrief

if TYPE_CHECKING:
    from pathlib import Path

    from orkestra.adapters.base import AgentAdapter
    from orkestra.policy import PolicyEngine
    from orkestra.schemas.capability import CapabilityMatrix

M = TypeVar("M", bound=BaseModel)


class DirectorService:
    def __init__(
        self,
        director_name: str,
        adapter: AgentAdapter,
        policy: PolicyEngine,
        work_dir: Path,
        *,
        max_retries: int = 2,
        timeout_s: int = 600,
        offline: bool = False,
    ) -> None:
        self.director_name = director_name
        self.adapter = adapter
        self.policy = policy
        self.work_dir = work_dir
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.offline = offline

    # ----------------------------------------------------------- plumbing

    async def _ask(self, prompt: str, model: type[M], task_id: str) -> M:
        """One structured exchange with bounded schema-repair retries."""
        last_error = ""
        for attempt in range(self.max_retries + 1):
            instructions = prompt
            if attempt > 0:
                instructions = (
                    f"{prompt}\n\nYour previous response was invalid: {last_error}\n"
                    "Respond again with ONE valid JSON object only."
                )
            brief = TaskBrief(
                task_id=f"{task_id}-r{attempt}",
                run_id="director",
                title=f"director:{task_id}",
                kind=TaskKind.PLAN,
                instructions=instructions,
                cwd=str(self.work_dir),
                timeout_s=self.timeout_s,
                json_schema=model.model_json_schema(),
            )
            result = await run_invocation(
                self.adapter.build_invocation(brief),
                self.adapter.make_parser(brief),
                lambda _e: None,
            )
            if not result.ok:
                last_error = f"{result.error_kind.value}: {result.error_detail[:300]}"
                continue
            payload = result.structured
            if payload is None:
                payload = extract_json_object(result.final_text)
            if payload is None:
                last_error = "no JSON object found in response"
                continue
            try:
                return model.model_validate(payload)
            except ValidationError as exc:
                last_error = str(exc)[:800]
        msg = (
            f"director {self.director_name!r} failed {task_id} after "
            f"{self.max_retries + 1} attempts: {last_error}"
        )
        raise DirectorError(msg)

    # ---------------------------------------------------------- decisions

    async def analyze(self, spec_text: str, agents_summary: str) -> DirectorAnalysis:
        if self.offline:
            return heuristic_analysis(spec_text)
        try:
            return await self._ask(
                prompts.ANALYZE.format(agents=agents_summary, spec=spec_text[:16000]),
                DirectorAnalysis,
                "analyze",
            )
        except DirectorError:
            return heuristic_analysis(spec_text)

    async def plan(
        self,
        spec_text: str,
        analysis: DirectorAnalysis,
        matrix: CapabilityMatrix,
        agents: list[str],
        verify_commands: list[str],
    ) -> DirectorPlan:
        if self.offline:
            return heuristic_plan(spec_text, agents, matrix, verify_commands)
        prompt = prompts.PLAN.format(
            agents=", ".join(agents),
            matrix=matrix.model_dump_json(),
            analysis=analysis.model_dump_json(),
            spec=spec_text[:16000],
        )
        try:
            plan = await self._ask(prompt, DirectorPlan, "plan")
            self.validate_plan(plan, agents)
        except DirectorError:
            return heuristic_plan(spec_text, agents, matrix, verify_commands)
        return plan

    async def challenge(
        self, plan: DirectorPlan, challenger_name: str, challenger: AgentAdapter
    ) -> PlanChallenge:
        brief_prompt = prompts.CHALLENGE.format(
            agent=challenger_name, plan=plan.model_dump_json()
        )
        service = DirectorService(
            challenger_name, challenger, self.policy, self.work_dir,
            max_retries=1, timeout_s=self.timeout_s, offline=self.offline,
        )
        if self.offline:
            return PlanChallenge(agent=challenger_name, verdict="accept")
        try:
            result = await service._ask(brief_prompt, PlanChallenge, "challenge")
        except DirectorError:
            return PlanChallenge(
                agent=challenger_name,
                verdict="accept",
                concerns=["challenger unavailable; challenge skipped"],
            )
        return result.model_copy(update={"agent": challenger_name})

    async def revise_plan(
        self,
        plan: DirectorPlan,
        challenges: list[PlanChallenge],
        agents: list[str],
        spec_text: str,
        matrix: CapabilityMatrix,
        verify_commands: list[str],
    ) -> DirectorPlan:
        substantive = [c for c in challenges if c.verdict == "revise"]
        if not substantive or self.offline:
            return plan
        prompt = prompts.REVISE_PLAN.format(
            plan=plan.model_dump_json(),
            challenges=json.dumps([c.model_dump() for c in substantive]),
            agents=", ".join(agents),
        )
        try:
            revised = await self._ask(prompt, DirectorPlan, "revise-plan")
            self.validate_plan(revised, agents)
        except DirectorError:
            return plan  # keep the already-validated original
        return revised

    async def reassign(
        self,
        title: str,
        kind: str,
        failures: str,
        matrix: CapabilityMatrix,
    ) -> ReassignmentAdvice:
        if self.offline:
            return ReassignmentAdvice(escalate_to_human=True,
                                      reason="offline mode: escalating after failures")
        prompt = prompts.REASSIGN.format(
            matrix=matrix.model_dump_json(), title=title, kind=kind, failures=failures
        )
        try:
            return await self._ask(prompt, ReassignmentAdvice, "reassign")
        except DirectorError:
            return ReassignmentAdvice(
                escalate_to_human=True,
                reason="director unavailable for reassignment decision",
            )

    # --------------------------------------------------------- validation

    def validate_plan(self, plan: DirectorPlan, agents: list[str]) -> None:
        """Kernel-side validation of a proposed plan (raises DirectorError)."""
        if not plan.tasks:
            msg = "plan contains no tasks"
            raise DirectorError(msg)
        if len(plan.tasks) > 25:
            msg = f"plan has {len(plan.tasks)} tasks; limit is 25"
            raise DirectorError(msg)
        keys = [p.task.key for p in plan.tasks]
        try:
            TaskDag(
                deps={p.task.key: p.task.depends_on for p in plan.tasks},
                all_keys=keys,
            )
        except Exception as exc:
            msg = f"plan graph invalid: {exc}"
            raise DirectorError(msg) from exc
        for planned in plan.tasks:
            decision = self.policy.check_assignment(planned.assignment)
            if not decision.allowed:
                msg = (
                    f"plan assignment for task {planned.task.key!r} violates policy: "
                    + "; ".join(decision.violations)
                )
                raise DirectorError(msg)
            unknown = [
                a
                for a in (
                    planned.assignment.primary,
                    *planned.assignment.reviewers,
                    *planned.assignment.fallbacks,
                )
                if a not in agents
            ]
            if unknown:
                msg = f"plan references unknown agents: {unknown}"
                raise DirectorError(msg)

"""Run preparation: analyze → probe → plan → challenge → finalize.

Turns a specification into a persisted, policy-validated task graph and
a ready-to-execute run. All director output is schema-validated; the
final plan passes kernel validation before anything is persisted.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from orkestra.capabilities import run_probes
from orkestra.capabilities.matrix import build_matrix
from orkestra.schemas.agent import EventKind
from orkestra.schemas.common import RunState

if TYPE_CHECKING:
    from orkestra.director import DirectorService
    from orkestra.kernel.scheduler import Orchestrator
    from orkestra.schemas.director import DirectorPlan


async def prepare_run(
    orch: Orchestrator,
    director: DirectorService,
    spec_text: str,
    *,
    max_challengers: int = 2,
) -> str:
    """Create, analyze, probe, and plan a run. Returns the run id."""
    config = orch.config
    # Fail fast on repository problems BEFORE any quota is spent on
    # analysis or probes.
    await orch.workspaces.validate_repository()
    run_id = orch.store.create_run(config.project.name)
    orch.director_service = director
    try:
        await _prepare(orch, director, run_id, spec_text, max_challengers)
    except BaseException:
        # Never leave a half-prepared run looking executable.
        orch.store.set_run_state(run_id, RunState.FAILED)
        raise
    return run_id


async def _prepare(
    orch: Orchestrator,
    director: DirectorService,
    run_id: str,
    spec_text: str,
    max_challengers: int,
) -> None:
    config = orch.config

    # Inventory before anything else; recorded for the report.
    summary = await orch.inventory_agents()
    orch.store.update_run_payload(run_id, agents=summary)
    unavailable = [n for n, s in summary.items() if s["available"] != "True"]
    if unavailable:
        orch.emit(run_id, EventKind.WARNING, f"agents unavailable: {', '.join(unavailable)}")

    # 1. Analyze.
    orch.store.set_run_state(run_id, RunState.ANALYZING, expected=(RunState.CREATED,))
    agents_summary = "\n".join(
        f"- {name}: {s['adapter']} {s['version']} (auth_ready={s['auth_ready']})"
        for name, s in summary.items()
    )
    analysis = await director.analyze(spec_text, agents_summary)
    orch.store.update_run_payload(run_id, analysis=analysis.model_dump(mode="json"))
    orch.emit(run_id, EventKind.COMPLETED, f"analysis: {analysis.summary[:400]}")

    # 2. Probe capabilities (bounded, cached, optional).
    orch.store.set_run_state(run_id, RunState.PROBING, expected=(RunState.ANALYZING,))
    usable_agents = {
        name: adapter
        for name, adapter in orch.adapters.items()
        if summary[name]["available"] == "True" and summary[name]["auth_ready"] == "True"
    }
    # Probes run in a scratch directory, never the project root — probe
    # prompts don't mutate files, but agents get no chance to.
    probe_dir = orch.root / ".orkestra" / "probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_observations = await run_probes(
        usable_agents,
        {n: summary[n]["version"] for n in usable_agents},
        orch.store,
        probe_dir,
        mode=config.probes.mode,
        budget=config.probes.budget,
        timeout_s=config.probes.timeout_s,
    )
    orch.emit(
        run_id,
        EventKind.COMPLETED,
        f"capability probes: {len(probe_observations)} observations (mode={config.probes.mode})",
    )

    # 3. Matrix from ALL evidence (probes + prior task history).
    observations = []
    for agent in orch.adapters:
        observations.extend(orch.store.observations_for(agent))
    matrix = build_matrix(observations)
    orch.store.update_run_payload(run_id, matrix=matrix.model_dump(mode="json"))

    # 4. Plan, challenge, revise, validate.
    orch.store.set_run_state(run_id, RunState.PLANNING, expected=(RunState.PROBING,))
    agent_names = list(config.enabled_agents.keys())
    plan = await director.plan(spec_text, analysis, matrix, agent_names, config.verify.commands)
    director.validate_plan(plan, agent_names)

    challengers = [
        (name, orch.adapters[name]) for name in usable_agents if name != director.director_name
    ][:max_challengers]
    challenges = []
    for challenger_name, challenger_adapter in challengers:
        challenge = await director.challenge(plan, challenger_name, challenger_adapter)
        challenges.append(challenge)
        orch.emit(
            run_id,
            EventKind.COMPLETED,
            f"plan challenge from {challenger_name}: {challenge.verdict} "
            f"({len(challenge.concerns)} concerns)",
        )
    plan = await director.revise_plan(
        plan, challenges, agent_names, spec_text, matrix, config.verify.commands
    )
    director.validate_plan(plan, agent_names)
    orch.store.update_run_payload(
        run_id,
        plan_notes=plan.notes,
        challenges=[c.model_dump(mode="json") for c in challenges],
    )

    # 5. Persist tasks and set up Git.
    base, integration = await orch.workspaces.start_run(run_id)
    orch.store.set_run_git(run_id, base, integration)
    for planned in plan.tasks:
        orch.store.add_task(run_id, planned.task, planned.assignment)
    orch.emit(
        run_id,
        EventKind.COMPLETED,
        f"plan finalized: {len(plan.tasks)} tasks "
        f"({json.dumps([p.task.key for p in plan.tasks])}); "
        f"integration branch {integration}",
    )


def plan_summary(plan: DirectorPlan) -> str:
    lines = []
    for planned in plan.tasks:
        deps = f" <- {', '.join(planned.task.depends_on)}" if planned.task.depends_on else ""
        lines.append(
            f"{planned.task.key} [{planned.task.kind.value}] "
            f"primary={planned.assignment.primary} "
            f"reviewers={','.join(planned.assignment.reviewers)}{deps}"
        )
    return "\n".join(lines)

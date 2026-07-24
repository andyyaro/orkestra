"""Bounded, quota-respecting capability probes.

Each probe is a single short prompt with a deterministic, objective
check evaluated by this harness — no self-reported scores (§6.8).
Results are cached as observations keyed by (agent, version, probe id);
``mode="cached"`` reuses them, ``mode="off"`` skips probing entirely.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from orkestra.adapters.jsonl import extract_json_object
from orkestra.adapters.runner import run_invocation
from orkestra.schemas.capability import CapabilityObservation, CapabilityProbe
from orkestra.schemas.common import TaskKind
from orkestra.schemas.task import TaskBrief

if TYPE_CHECKING:
    from pathlib import Path

    from orkestra.adapters.base import AgentAdapter
    from orkestra.store import Store

STANDARD_PROBES: list[CapabilityProbe] = [
    CapabilityProbe(
        probe_id="json-discipline-1",
        capability="structured_output",
        kind=TaskKind.PLAN,
        prompt=(
            'Return exactly this JSON object and nothing else: {"status": "ready", "count": 3}'
        ),
        expected_kind="json",
        check='parsed == {"status": "ready", "count": 3}',
    ),
    CapabilityProbe(
        probe_id="code-reasoning-1",
        capability="code_reasoning",
        kind=TaskKind.REVIEW,
        prompt=(
            "Given this Python function:\n\n"
            "def f(n):\n    return n * 2 + 1 if n % 2 == 0 else n - 1\n\n"
            'What does f(4) return? Reply with JSON: {"answer": <number>}'
        ),
        expected_kind="json",
        check='parsed.get("answer") == 9',
    ),
    CapabilityProbe(
        probe_id="instruction-following-1",
        capability="instruction_following",
        kind=TaskKind.IMPLEMENT,
        prompt="Reply with exactly the word ORKESTRA-READY and nothing else.",
        expected_kind="text",
        check='"ORKESTRA-READY" in text and len(text.strip()) < 40',
    ),
    CapabilityProbe(
        probe_id="bugspot-1",
        capability="bug_detection",
        kind=TaskKind.REVIEW,
        prompt=(
            "This Python function should return the maximum value in a list "
            "but has a bug:\n\n"
            "def find_max(xs):\n    m = 0\n    for x in xs:\n        if x > m:\n"
            "            m = x\n    return m\n\n"
            'Which input class breaks it? Reply JSON: {"breaks_on": "<short answer>"}'
        ),
        expected_kind="json",
        check='"negative" in json.dumps(parsed).lower()',
    ),
]


def _evaluate(probe: CapabilityProbe, text: str) -> bool:
    """Deterministically evaluate a probe's objective check."""
    parsed = extract_json_object(text) if probe.expected_kind == "json" else None
    if probe.expected_kind == "json" and parsed is None:
        return False
    namespace = {"parsed": parsed, "text": text, "json": json}
    safe_builtins = {"len": len, "str": str, "int": int, "float": float, "abs": abs}
    try:
        # Checks are Orkestra-authored constants, not external input.
        return bool(
            eval(probe.check, {"__builtins__": safe_builtins}, namespace)  # noqa: S307  # nosec B307 - Orkestra-authored constants
        )
    except Exception:
        return False


async def run_probes(
    adapters: dict[str, AgentAdapter],
    versions: dict[str, str],
    store: Store,
    work_dir: Path,
    *,
    mode: str = "cached",
    budget: int = 6,
    timeout_s: int = 240,
    probes: list[CapabilityProbe] | None = None,
) -> list[CapabilityObservation]:
    """Run (or reuse) probes for each agent within the budget."""
    if mode == "off":
        return []
    probe_set = probes if probes is not None else STANDARD_PROBES
    observations: list[CapabilityObservation] = []
    spent = 0
    for agent_name, adapter in adapters.items():
        version = versions.get(agent_name, "")
        for probe in probe_set:
            source = f"probe:{probe.probe_id}"
            if mode == "cached":
                cached = [
                    o
                    for o in store.observations_for(
                        agent_name, probe.capability, agent_version=version
                    )
                    if o.source == source
                ]
                if cached:
                    observations.extend(cached)
                    continue
            if spent >= budget:
                break
            spent += 1
            brief = TaskBrief(
                task_id=f"probe-{probe.probe_id}",
                run_id="probes",
                title=f"capability probe {probe.probe_id}",
                kind=probe.kind,
                instructions=probe.prompt,
                cwd=str(work_dir),
                timeout_s=timeout_s,
                json_schema={"type": "object"} if probe.expected_kind == "json" else None,
            )
            start = time.monotonic()
            try:
                result = await run_invocation(
                    adapter.build_invocation(brief),
                    adapter.make_parser(brief),
                    lambda _e: None,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                result = None
            passed = False
            if result is not None and result.ok:
                text = result.final_text
                if result.structured is not None:
                    text = json.dumps(result.structured)
                passed = _evaluate(probe, text)
            observation = CapabilityObservation(
                agent=agent_name,
                agent_version=version,
                capability=probe.capability,
                source=source,
                objective_pass=passed,
                latency_s=time.monotonic() - start,
            )
            store.add_observation(observation)
            observations.append(observation)
    return observations

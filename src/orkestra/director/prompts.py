"""Versioned director prompt templates.

Every prompt demands a single JSON object conforming to the supplied
schema; the kernel validates with Pydantic and re-requests on failure
(bounded). Free prose is never executed.
"""

from __future__ import annotations

PROMPT_VERSION = 1

ANALYZE = """\
You are the director of a multi-agent software project run by Orkestra,
a deterministic orchestrator. Analyze the project specification below and
the available agents, then respond with ONE JSON object matching the
provided schema (fields: summary, assumptions, risks, capability_demands).

capability_demands maps capability names to importance weights 0..1.
Use capability names from this vocabulary where applicable:
implementation, bug_detection, structured_output, research,
documentation, code_reasoning, instruction_following.

Available agents (name: adapter, version):
{agents}

Project specification:
---
{spec}
---
Respond with JSON only.
"""

PLAN = """\
You are the director of a multi-agent software project run by Orkestra.
Decompose the specification into 2-10 tasks forming a dependency graph
(DAG), and assign each task a primary agent, at least one independent
reviewer (never the same agent as the primary), and fallback agents.

Rules you must respect (the orchestrator enforces them and will reject
violations):
- task keys: lowercase slugs, unique
- depends_on refers to task keys defined in this plan; no cycles
- every assignment: primary != each reviewer; only these agents exist:
{agents}
- kinds: research | plan | implement | test | review | debug | integrate | document
- tasks of kind implement/test/debug/document mutate the repository
- keep descriptions self-contained: the assigned agent sees ONLY your
  description plus the workspace, not this conversation

Evidence — capability matrix (agent -> capability -> score/confidence):
{matrix}

Prior analysis:
{analysis}

Project specification:
---
{spec}
---
Respond with ONE JSON object matching the provided schema (a "tasks"
array of {{task, assignment}} objects plus "notes"). JSON only.
"""

CHALLENGE = """\
You are agent {agent} reviewing a project plan proposed by the director
of a multi-agent run. Identify missing dependencies, unclear task
descriptions, unrealistic assignments, and risks. Be specific and brief.

The plan (JSON):
{plan}

Respond with ONE JSON object matching the provided schema (fields:
concerns, suggested_changes, verdict where verdict is "accept" or
"revise"). JSON only.
"""

REVISE_PLAN = """\
You are the director. Other agents challenged your plan; incorporate the
valid concerns and produce the final plan under the same rules as before.

Your previous plan:
{plan}

Challenges:
{challenges}

Rules reminder — agents: {agents}; primary != reviewer; DAG over defined
task keys; 2-10 tasks. Respond with ONE JSON object matching the provided
schema. JSON only.
"""

REVIEW = """\
You are an independent code reviewer in a multi-agent run. Another agent
implemented the task below in this workspace. Review the changes CRITICALLY:
correctness, completeness against the task, tests, and safety. You are the
last line of defense before integration; do not rubber-stamp.

Task: {title}
Task description:
{description}

Changed files (relative to the task base commit):
{changed}

Diff summary:
{diffstat}

Inspect files in the workspace as needed. Respond with ONE JSON object
matching the provided schema (fields: approve, findings, required_changes,
severity in none|low|medium|high|critical). JSON only.
"""

FIX = """\
You are the implementing agent returning to your task after an
independent review requested changes. Address every required change,
keep working strictly inside this workspace.

Task: {title}
Original description:
{description}

Review findings:
{findings}

Required changes:
{required}
"""

REASSIGN = """\
You are the director. The task below failed repeatedly; decide what to do
next. Available agents and their evidence:
{matrix}

Task: {title} (kind: {kind})
Failure history:
{failures}

Respond with ONE JSON object matching the provided schema (fields:
reassign_to (agent name or null), change_kind (or null),
revised_instructions (or null), escalate_to_human (bool), reason).
JSON only.
"""

# Concepts

## Separation of powers

Orkestra's architecture rests on one idea: **intelligence proposes,
determinism disposes.**

- The **director** (an agent, default Claude Code) understands your spec,
  measures the other agents, decomposes work, and recommends who does
  what. Everything it says arrives as JSON validated against schemas.
- The **kernel** (plain Python, no LLM) is the only thing with authority:
  it owns state, dispatches work, enforces policy, runs verification,
  pairs reviewers, merges results, and decides when things are done. A
  hostile or confused model output cannot change policy — it can only be
  rejected.

## Runs, tasks, attempts

- A **run** is one execution of your specification: analysis → probes →
  plan → execution → report. Runs are persistent and resumable.
- A **task** is a node in the run's dependency graph (DAG), with a kind
  (`implement`, `test`, `review`, `research`, …), an assignment
  (primary, reviewers, fallbacks), and acceptance commands.
- An **attempt** is one agent's try at a task. Attempts are bounded by
  `max_attempts_per_task`; failures trigger backoff, fallback agents,
  director reassignment, and finally a human decision — in that order.

## Workspaces

Every mutating task gets a fresh **Git worktree** on its own branch
(`ork/<run>/<task>`), branched from the run's **integration branch**
(`ork/<run>/integration`). Agents cannot see each other's in-progress
work; the kernel commits whatever they changed, validates the diff
against path policy, and merges (no-ff) only after gates and review
pass. Your own branches are never written to.

## Verification gates

Acceptance commands come from your config or per-task from the plan.
The kernel runs them itself in the task's worktree and reads exit codes.
An agent claiming success has no effect; a failing gate sends the task
back with the failure context.

## Independent review

For every mutating task, a **different agent** reviews the diff in the
workspace and returns a structured verdict. `implementer ≠ reviewer` is
enforced by the kernel even when fallbacks shuffle assignments.
Review/fix loops are bounded by `max_review_cycles`.

## Capability matrix and the ledger

At run start, agents face small, objective **probes** (return exact
JSON, trace code, spot a bug). Results — plus the outcome of every real
task ever run in this project — become **observations**. The matrix
aggregates observations into scores with confidence values, and every
score lists its evidence. Assignments rank candidates by evidenced
score; the director sees the matrix when planning; outcomes feed back
after every task. No evidence → no score → conservative defaults.

## Human gates

Orkestra only asks you things it genuinely cannot decide: exhausted
budgets, policy walls, missing auth. A decision record carries the
question, why it's blocked, concrete options with consequences, and a
recommendation. Unblocked work continues in parallel. `orkestra
decisions` → `orkestra approve` → `orkestra resume`.

## Offline mode

`--offline` replaces the director with a deterministic heuristic planner
and skips all LLM calls — useful for trying the machinery, testing
configs, and running fake/external agents in CI.

"""Repositories over the SQLite schema.

State-changing methods take an *expected* prior state where relevant and
raise ``StateTransitionError`` on mismatch — transitions are idempotent
and safe to retry after a crash (threat T13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from orkestra.errors import StateTransitionError, StoreError
from orkestra.ids import new_id
from orkestra.redact import redact
from orkestra.schemas.agent import AgentEvent, AgentResult, Usage
from orkestra.schemas.capability import CapabilityObservation
from orkestra.schemas.common import AttemptState, RunState, TaskState, utc_now
from orkestra.schemas.decision import HumanDecision
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.store.db import Database


def _now() -> str:
    return utc_now().isoformat()


@dataclass(frozen=True)
class RunRow:
    run_id: str
    project_name: str
    state: RunState
    base_commit: str
    integration_branch: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    run_id: str
    key: str
    state: TaskState
    spec: TaskSpec
    assignment: Assignment | None
    attempt_count: int
    review_cycles: int


@dataclass(frozen=True)
class AttemptRow:
    attempt_id: str
    task_id: str
    run_id: str
    agent: str
    role: str
    state: AttemptState
    workspace: str
    result: AgentResult | None


@dataclass(frozen=True)
class WorkspaceRow:
    workspace_id: str
    run_id: str
    task_id: str
    path: str
    branch: str
    base_commit: str
    state: str


class Store:
    """All persistence operations used by the kernel and CLI."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------- runs

    def create_run(self, project_name: str, payload: dict[str, Any] | None = None) -> str:
        run_id = new_id("run")
        now = _now()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, project_name, state, created_at, updated_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, project_name, RunState.CREATED.value, now, now, json.dumps(payload or {})),
            )
        return run_id

    def get_run(self, run_id: str) -> RunRow:
        row = self.db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            msg = f"run not found: {run_id}"
            raise StoreError(msg)
        return RunRow(
            run_id=row["run_id"],
            project_name=row["project_name"],
            state=RunState(row["state"]),
            base_commit=row["base_commit"],
            integration_branch=row["integration_branch"],
            payload=json.loads(row["payload"]),
        )

    def latest_run(self) -> RunRow | None:
        row = self.db.query_one("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1")
        return self.get_run(row["run_id"]) if row else None

    def set_run_state(
        self, run_id: str, new: RunState, expected: tuple[RunState, ...] | None = None
    ) -> None:
        with self.db.tx() as conn:
            row = conn.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                msg = f"run not found: {run_id}"
                raise StoreError(msg)
            current = RunState(row["state"])
            if current == new:
                return  # idempotent
            if expected is not None and current not in expected:
                msg = f"run {run_id}: cannot move {current} -> {new} (expected {expected})"
                raise StateTransitionError(msg)
            conn.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (new.value, _now(), run_id),
            )

    def set_run_git(self, run_id: str, base_commit: str, integration_branch: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE runs SET base_commit = ?, integration_branch = ?, updated_at = ?"
                " WHERE run_id = ?",
                (base_commit, integration_branch, _now(), run_id),
            )

    def update_run_payload(self, run_id: str, **updates: Any) -> None:
        with self.db.tx() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                msg = f"run not found: {run_id}"
                raise StoreError(msg)
            payload = json.loads(row["payload"])
            payload.update(updates)
            conn.execute(
                "UPDATE runs SET payload = ?, updated_at = ? WHERE run_id = ?",
                (json.dumps(payload), _now(), run_id),
            )

    # ------------------------------------------------------------ tasks

    def add_task(self, run_id: str, spec: TaskSpec, assignment: Assignment | None) -> str:
        task_id = new_id("task")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, run_id, key, state, kind, payload,"
                " assignment, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    run_id,
                    spec.key,
                    TaskState.PENDING.value,
                    spec.kind.value,
                    spec.model_dump_json(),
                    assignment.model_dump_json() if assignment else "{}",
                    _now(),
                ),
            )
            for dep in spec.depends_on:
                conn.execute(
                    "INSERT OR IGNORE INTO task_deps (run_id, task_key, depends_on_key)"
                    " VALUES (?, ?, ?)",
                    (run_id, spec.key, dep),
                )
        return task_id

    def _task_from_row(self, row: Any) -> TaskRow:
        assignment_raw = json.loads(row["assignment"])
        return TaskRow(
            task_id=row["task_id"],
            run_id=row["run_id"],
            key=row["key"],
            state=TaskState(row["state"]),
            spec=TaskSpec.model_validate_json(row["payload"]),
            assignment=Assignment.model_validate(assignment_raw) if assignment_raw else None,
            attempt_count=row["attempt_count"],
            review_cycles=row["review_cycles"],
        )

    def get_task(self, task_id: str) -> TaskRow:
        row = self.db.query_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        if row is None:
            msg = f"task not found: {task_id}"
            raise StoreError(msg)
        return self._task_from_row(row)

    def tasks_for_run(self, run_id: str) -> list[TaskRow]:
        rows = self.db.query("SELECT * FROM tasks WHERE run_id = ? ORDER BY task_id", (run_id,))
        return [self._task_from_row(r) for r in rows]

    def deps_for_run(self, run_id: str) -> dict[str, list[str]]:
        rows = self.db.query(
            "SELECT task_key, depends_on_key FROM task_deps WHERE run_id = ?", (run_id,)
        )
        deps: dict[str, list[str]] = {}
        for r in rows:
            deps.setdefault(r["task_key"], []).append(r["depends_on_key"])
        return deps

    def set_task_state(
        self, task_id: str, new: TaskState, expected: tuple[TaskState, ...] | None = None
    ) -> None:
        with self.db.tx() as conn:
            row = conn.execute("SELECT state FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                msg = f"task not found: {task_id}"
                raise StoreError(msg)
            current = TaskState(row["state"])
            if current == new:
                return
            if expected is not None and current not in expected:
                msg = f"task {task_id}: cannot move {current} -> {new} (expected {expected})"
                raise StateTransitionError(msg)
            conn.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE task_id = ?",
                (new.value, _now(), task_id),
            )

    def set_task_assignment(self, task_id: str, assignment: Assignment) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE tasks SET assignment = ?, updated_at = ? WHERE task_id = ?",
                (assignment.model_dump_json(), _now(), task_id),
            )

    def bump_task_counter(self, task_id: str, column: str) -> int:
        if column not in ("attempt_count", "review_cycles"):
            msg = f"invalid counter column: {column}"
            raise StoreError(msg)
        with self.db.tx() as conn:
            conn.execute(
                f"UPDATE tasks SET {column} = {column} + 1, updated_at = ?"  # noqa: S608  # nosec B608 - column allowlisted above
                " WHERE task_id = ?",
                (_now(), task_id),
            )
            row = conn.execute(
                f"SELECT {column} AS n FROM tasks WHERE task_id = ?",  # noqa: S608  # nosec B608 - column allowlisted above
                (task_id,),
            ).fetchone()
        return int(row["n"])

    # --------------------------------------------------------- attempts

    def create_attempt(
        self, task_id: str, run_id: str, agent: str, role: str, workspace: str = ""
    ) -> str:
        attempt_id = new_id("att")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO attempts (attempt_id, task_id, run_id, agent, role, state,"
                " started_at, workspace) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    task_id,
                    run_id,
                    agent,
                    role,
                    AttemptState.RUNNING.value,
                    _now(),
                    workspace,
                ),
            )
        return attempt_id

    def finish_attempt(
        self, attempt_id: str, state: AttemptState, result: AgentResult | None
    ) -> None:
        with self.db.tx() as conn:
            row = conn.execute(
                "SELECT state FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                msg = f"attempt not found: {attempt_id}"
                raise StoreError(msg)
            if AttemptState(row["state"]) not in (AttemptState.RUNNING,):
                return  # already terminal — idempotent
            conn.execute(
                "UPDATE attempts SET state = ?, finished_at = ?, result = ? WHERE attempt_id = ?",
                (state.value, _now(), result.model_dump_json() if result else None, attempt_id),
            )

    def _attempt_from_row(self, row: Any) -> AttemptRow:
        return AttemptRow(
            attempt_id=row["attempt_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            agent=row["agent"],
            role=row["role"],
            state=AttemptState(row["state"]),
            workspace=row["workspace"],
            result=AgentResult.model_validate_json(row["result"]) if row["result"] else None,
        )

    def attempts_for_task(self, task_id: str) -> list[AttemptRow]:
        rows = self.db.query(
            "SELECT * FROM attempts WHERE task_id = ? ORDER BY started_at", (task_id,)
        )
        return [self._attempt_from_row(r) for r in rows]

    def running_attempts(self, run_id: str) -> list[AttemptRow]:
        rows = self.db.query(
            "SELECT * FROM attempts WHERE run_id = ? AND state = ?",
            (run_id, AttemptState.RUNNING.value),
        )
        return [self._attempt_from_row(r) for r in rows]

    def mark_interrupted(self, attempt_id: str) -> None:
        self.finish_attempt(attempt_id, AttemptState.INTERRUPTED, None)

    # ----------------------------------------------------------- events

    def append_event(
        self,
        run_id: str,
        event: AgentEvent,
        task_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO events (run_id, task_id, attempt_id, ts, kind, text, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    task_id,
                    attempt_id,
                    event.ts.isoformat(),
                    event.kind.value,
                    redact(event.text)[:20_000],
                    redact(json.dumps(event.data))[:50_000],
                ),
            )

    def events_for_run(
        self, run_id: str, limit: int = 200, task_id: str | None = None
    ) -> list[dict[str, Any]]:
        if task_id:
            rows = self.db.query(
                "SELECT * FROM events WHERE run_id = ? AND task_id = ?"
                " ORDER BY event_id DESC LIMIT ?",
                (run_id, task_id, limit),
            )
        else:
            rows = self.db.query(
                "SELECT * FROM events WHERE run_id = ? ORDER BY event_id DESC LIMIT ?",
                (run_id, limit),
            )
        return [dict(r) for r in reversed(rows)]

    # -------------------------------------------------------- decisions

    def add_decision(self, decision: HumanDecision) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO decisions (decision_id, run_id, resolved, payload)"
                " VALUES (?, ?, ?, ?)",
                (
                    decision.decision_id,
                    decision.run_id,
                    int(decision.resolved),
                    decision.model_dump_json(),
                ),
            )

    def get_decision(self, decision_id: str) -> HumanDecision:
        row = self.db.query_one(
            "SELECT payload FROM decisions WHERE decision_id = ?", (decision_id,)
        )
        if row is None:
            msg = f"decision not found: {decision_id}"
            raise StoreError(msg)
        return HumanDecision.model_validate_json(row["payload"])

    def decisions_for_run(self, run_id: str, unresolved_only: bool = False) -> list[HumanDecision]:
        sql = "SELECT payload FROM decisions WHERE run_id = ?"
        if unresolved_only:
            sql += " AND resolved = 0"
        return [
            HumanDecision.model_validate_json(r["payload"]) for r in self.db.query(sql, (run_id,))
        ]

    def resolve_decision(self, decision_id: str, option: str, note: str = "") -> HumanDecision:
        decision = self.get_decision(decision_id)
        if decision.resolved:
            msg = f"decision {decision_id} already resolved as {decision.chosen_option!r}"
            raise StateTransitionError(msg)
        if option not in {o.key for o in decision.options}:
            valid = ", ".join(o.key for o in decision.options)
            msg = f"invalid option {option!r} for decision {decision_id} (valid: {valid})"
            raise StoreError(msg)
        resolved = decision.model_copy(
            update={"chosen_option": option, "note": note, "resolved_at": utc_now()}
        )
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE decisions SET resolved = 1, payload = ? WHERE decision_id = ?",
                (resolved.model_dump_json(), decision_id),
            )
        return resolved

    # ----------------------------------------------- capability records

    def add_observation(self, obs: CapabilityObservation) -> str:
        observation_id = new_id("obs")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO observations (observation_id, agent, agent_version,"
                " capability, source, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    observation_id,
                    obs.agent,
                    obs.agent_version,
                    obs.capability,
                    obs.source,
                    obs.model_dump_json(),
                    _now(),
                ),
            )
        return observation_id

    def observations_for(
        self, agent: str, capability: str | None = None, agent_version: str | None = None
    ) -> list[CapabilityObservation]:
        sql = "SELECT payload FROM observations WHERE agent = ?"
        params: list[object] = [agent]
        if capability is not None:
            sql += " AND capability = ?"
            params.append(capability)
        if agent_version is not None:
            sql += " AND agent_version = ?"
            params.append(agent_version)
        rows = self.db.query(sql, tuple(params))
        return [CapabilityObservation.model_validate_json(r["payload"]) for r in rows]

    # ------------------------------------------------------------ ledger

    def add_ledger_entry(
        self, run_id: str, agent: str, task_id: str, kind: str, outcome: str, detail: str = ""
    ) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO ledger (run_id, agent, task_id, kind, outcome, detail, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, agent, task_id, kind, outcome, detail[:2000], _now()),
            )

    def ledger_summary(self, agent: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT agent, kind, outcome, COUNT(*) AS n FROM ledger"
        params: tuple[object, ...] = ()
        if agent:
            sql += " WHERE agent = ?"
            params = (agent,)
        sql += " GROUP BY agent, kind, outcome ORDER BY agent, kind"
        return [dict(r) for r in self.db.query(sql, params)]

    # -------------------------------------------------------- workspaces

    def add_workspace(
        self, run_id: str, task_id: str, path: str, branch: str, base_commit: str
    ) -> str:
        workspace_id = new_id("ws")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO workspaces (workspace_id, run_id, task_id, path, branch,"
                " base_commit, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (workspace_id, run_id, task_id, path, branch, base_commit, _now()),
            )
        return workspace_id

    def set_workspace_state(self, workspace_id: str, state: str) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE workspaces SET state = ? WHERE workspace_id = ?",
                (state, workspace_id),
            )

    def workspaces_for_run(self, run_id: str, state: str | None = None) -> list[WorkspaceRow]:
        sql = "SELECT * FROM workspaces WHERE run_id = ?"
        params: list[object] = [run_id]
        if state:
            sql += " AND state = ?"
            params.append(state)
        return [
            WorkspaceRow(
                workspace_id=r["workspace_id"],
                run_id=r["run_id"],
                task_id=r["task_id"],
                path=r["path"],
                branch=r["branch"],
                base_commit=r["base_commit"],
                state=r["state"],
            )
            for r in self.db.query(sql, tuple(params))
        ]

    # ------------------------------------------------------------- usage

    def add_usage(self, run_id: str, agent: str, attempt_id: str | None, usage: Usage) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO usage_log (run_id, agent, attempt_id, input_tokens,"
                " output_tokens, total_cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    agent,
                    attempt_id,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.total_cost_usd,
                    _now(),
                ),
            )

    def usage_summary(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT agent, SUM(input_tokens) AS input_tokens,"
            " SUM(output_tokens) AS output_tokens, SUM(total_cost_usd) AS total_cost_usd,"
            " COUNT(*) AS calls FROM usage_log WHERE run_id = ? GROUP BY agent",
            (run_id,),
        )
        return [dict(r) for r in rows]

"""Unit tests: persistence — migrations, transitions, idempotency, decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.errors import StateTransitionError, StoreError
from orkestra.schemas.agent import AgentEvent, AgentResult, EventKind, ResultStatus, Usage
from orkestra.schemas.common import AttemptState, RunState, TaskKind, TaskState
from orkestra.schemas.decision import DecisionOption, HumanDecision
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.store import Database, Store
from orkestra.store.migrations import MIGRATIONS


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(Database(tmp_path / "test.db"))


def make_task(key: str = "t1", deps: list[str] | None = None) -> TaskSpec:
    return TaskSpec(key=key, title=key, kind=TaskKind.IMPLEMENT, depends_on=deps or [])


class TestMigrations:
    def test_fresh_db_migrates(self, tmp_path: Path) -> None:
        db = Database(tmp_path / "a.db")
        row = db.query_one("SELECT version FROM schema_version")
        assert row is not None and row["version"] == len(MIGRATIONS)

    def test_reopen_is_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "b.db"
        Database(path).close()
        db2 = Database(path)  # must not re-run migration 1
        assert db2.query_one("SELECT version FROM schema_version")["version"] == len(MIGRATIONS)

    def test_future_schema_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "c.db"
        db = Database(path)
        with db.tx() as conn:
            conn.execute("UPDATE schema_version SET version = 99")
        db.close()
        with pytest.raises(StoreError, match="newer than this Orkestra"):
            Database(path)


class TestRunLifecycle:
    def test_create_and_get(self, store: Store) -> None:
        run_id = store.create_run("demo")
        run = store.get_run(run_id)
        assert run.state is RunState.CREATED
        assert run.project_name == "demo"

    def test_transition_guard(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.set_run_state(run_id, RunState.ANALYZING, expected=(RunState.CREATED,))
        with pytest.raises(StateTransitionError):
            store.set_run_state(run_id, RunState.COMPLETE, expected=(RunState.RUNNING,))

    def test_transition_idempotent(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.set_run_state(run_id, RunState.ANALYZING)
        # Same target twice: second call is a no-op even with a guard.
        store.set_run_state(run_id, RunState.ANALYZING, expected=(RunState.CREATED,))
        assert store.get_run(run_id).state is RunState.ANALYZING

    def test_missing_run(self, store: Store) -> None:
        with pytest.raises(StoreError, match="not found"):
            store.get_run("run_missing")


class TestTasks:
    def test_add_and_roundtrip(self, store: Store) -> None:
        run_id = store.create_run("demo")
        spec = make_task("build", deps=[])
        assignment = Assignment(primary="claude", reviewers=["codex"])
        task_id = store.add_task(run_id, spec, assignment)
        task = store.get_task(task_id)
        assert task.spec == spec
        assert task.assignment is not None
        assert task.assignment.primary == "claude"
        assert task.state is TaskState.PENDING

    def test_unique_key_per_run(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.add_task(run_id, make_task("dup"), None)
        with pytest.raises(Exception, match="UNIQUE"):
            store.add_task(run_id, make_task("dup"), None)

    def test_deps_persisted(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.add_task(run_id, make_task("a"), None)
        store.add_task(run_id, make_task("b", deps=["a"]), None)
        assert store.deps_for_run(run_id) == {"b": ["a"]}

    def test_counters(self, store: Store) -> None:
        run_id = store.create_run("demo")
        task_id = store.add_task(run_id, make_task(), None)
        assert store.bump_task_counter(task_id, "attempt_count") == 1
        assert store.bump_task_counter(task_id, "attempt_count") == 2
        with pytest.raises(StoreError, match="invalid counter"):
            store.bump_task_counter(task_id, "state")  # SQL injection guard


class TestAttempts:
    def test_lifecycle_and_idempotent_finish(self, store: Store) -> None:
        run_id = store.create_run("demo")
        task_id = store.add_task(run_id, make_task(), None)
        attempt_id = store.create_attempt(task_id, run_id, "claude", "primary")
        result = AgentResult(status=ResultStatus.OK, final_text="done")
        store.finish_attempt(attempt_id, AttemptState.SUCCEEDED, result)
        # Second finish (e.g. crash-recovery replay) must not overwrite.
        store.finish_attempt(attempt_id, AttemptState.FAILED, None)
        attempts = store.attempts_for_task(task_id)
        assert attempts[0].state is AttemptState.SUCCEEDED
        assert attempts[0].result is not None and attempts[0].result.ok

    def test_running_attempts_and_interrupt(self, store: Store) -> None:
        run_id = store.create_run("demo")
        task_id = store.add_task(run_id, make_task(), None)
        attempt_id = store.create_attempt(task_id, run_id, "codex", "primary")
        assert [a.attempt_id for a in store.running_attempts(run_id)] == [attempt_id]
        store.mark_interrupted(attempt_id)
        assert store.running_attempts(run_id) == []


class TestEventsAndRedaction:
    def test_events_redacted_at_write(self, store: Store) -> None:
        run_id = store.create_run("demo")
        event = AgentEvent(
            kind=EventKind.TEXT,
            text="found key sk-ant-api03-verysecretsecret in env",
        )
        store.append_event(run_id, event)
        rows = store.events_for_run(run_id)
        assert len(rows) == 1
        assert "verysecret" not in rows[0]["text"]
        assert "[REDACTED]" in rows[0]["text"]


class TestDecisions:
    def make_decision(self, store: Store, run_id: str) -> HumanDecision:
        decision = HumanDecision(
            decision_id="dec_1",
            run_id=run_id,
            question="Deploy to production?",
            why_blocked="production access is a human-gated action",
            options=[
                DecisionOption(key="yes", label="Deploy"),
                DecisionOption(key="no", label="Skip"),
            ],
            recommendation="no",
        )
        store.add_decision(decision)
        return decision

    def test_resolve(self, store: Store) -> None:
        run_id = store.create_run("demo")
        self.make_decision(store, run_id)
        resolved = store.resolve_decision("dec_1", "no", note="not today")
        assert resolved.resolved and resolved.chosen_option == "no"
        assert store.decisions_for_run(run_id, unresolved_only=True) == []

    def test_double_resolve_rejected(self, store: Store) -> None:
        run_id = store.create_run("demo")
        self.make_decision(store, run_id)
        store.resolve_decision("dec_1", "yes")
        with pytest.raises(StateTransitionError, match="already resolved"):
            store.resolve_decision("dec_1", "no")

    def test_invalid_option_rejected(self, store: Store) -> None:
        run_id = store.create_run("demo")
        self.make_decision(store, run_id)
        with pytest.raises(StoreError, match="invalid option"):
            store.resolve_decision("dec_1", "maybe")


class TestUsageAndLedger:
    def test_usage_summary(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.add_usage(
            run_id, "claude", None, Usage(input_tokens=10, output_tokens=5, total_cost_usd=0.01)
        )
        store.add_usage(run_id, "claude", None, Usage(input_tokens=20, output_tokens=15))
        [summary] = store.usage_summary(run_id)
        assert summary["input_tokens"] == 30
        assert summary["calls"] == 2

    def test_ledger(self, store: Store) -> None:
        run_id = store.create_run("demo")
        store.add_ledger_entry(run_id, "codex", "task_1", "implement", "succeeded")
        store.add_ledger_entry(run_id, "codex", "task_2", "implement", "failed")
        rows = store.ledger_summary("codex")
        outcomes = {r["outcome"]: r["n"] for r in rows}
        assert outcomes == {"succeeded": 1, "failed": 1}

"""End-to-end orchestration tests with fake agents over real Git repos.

Each test drives the real kernel: prepare (offline director → heuristic
plan) or a hand-built plan, then execute() with the full pipeline —
worktrees, deterministic commits, verification gates, independent
review, integration, ledger, decisions, resume.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orkestra.app import App
from orkestra.kernel.prepare import prepare_run
from orkestra.schemas.common import RunState, TaskKind, TaskState
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.workspace.git import GitRepo
from tests.e2e.conftest import agent_block, make_project

pytestmark = pytest.mark.e2e


async def manual_run(app: App, tasks: list[tuple[TaskSpec, Assignment]]) -> str:
    """Persist a hand-built plan and Git-prepare the run."""
    run_id = app.store.create_run(app.config.project.name)
    base, integration = await app.workspaces.start_run(run_id)
    app.store.set_run_git(run_id, base, integration)
    for spec, assignment in tasks:
        app.store.add_task(run_id, spec, assignment)
    return run_id


def spec(
    key: str,
    description: str,
    *,
    kind: TaskKind = TaskKind.IMPLEMENT,
    deps: list[str] | None = None,
    acceptance: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        key=key,
        title=key,
        kind=kind,
        description=description,
        depends_on=deps or [],
        acceptance=acceptance or [],
    )


def assign(primary: str, reviewer: str, fallbacks: list[str] | None = None) -> Assignment:
    return Assignment(primary=primary, reviewers=[reviewer], fallbacks=fallbacks or [])


async def show_integration_files(app: App, run_id: str) -> str:
    repo = GitRepo(app.root)
    _, out, _ = await repo._git("ls-tree", "-r", "--name-only", f"ork/{run_id}/integration")
    return out


class TestTwoAgentRun:
    async def test_full_prepared_run_succeeds(self, app: App) -> None:
        run_id = await prepare_run(app.orchestrator, app.director, "# Demo\nBuild a demo")
        tasks = app.store.tasks_for_run(run_id)
        assert {t.key for t in tasks} == {"implement", "test", "document"}
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        for task in app.store.tasks_for_run(run_id):
            assert task.state is TaskState.DONE
        files = await show_integration_files(app, run_id)
        assert "fake-" in files  # fake agents' work integrated
        # Ledger recorded outcomes for both agents.
        summary = app.store.ledger_summary()
        agents_seen = {row["agent"] for row in summary}
        assert {"alpha", "beta"} <= agents_seen
        # Usage recorded.
        assert app.store.usage_summary(run_id)

    async def test_review_separation_enforced_in_attempts(self, app: App) -> None:
        run_id = await prepare_run(app.orchestrator, app.director, "# Demo")
        await app.orchestrator.execute(run_id)
        for task in app.store.tasks_for_run(run_id):
            attempts = app.store.attempts_for_task(task.task_id)
            implementers = {a.agent for a in attempts if a.role == "primary"}
            reviewers = {a.agent for a in attempts if a.role == "reviewer"}
            assert not (implementers & reviewers), f"task {task.key}: agent reviewed its own work"


class TestManyAgents:
    async def test_three_agents(self, tmp_path: Path) -> None:
        app = await make_project(tmp_path, ["alpha", "beta", "gamma"])
        run_id = await prepare_run(app.orchestrator, app.director, "# Demo3")
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        app.close()

    async def test_five_agents_no_fixed_three_assumption(self, tmp_path: Path) -> None:
        app = await make_project(
            tmp_path, ["alpha", "beta", "gamma", "delta", "epsilon"], concurrency=3
        )
        run_id = await prepare_run(app.orchestrator, app.director, "# Demo5")
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        primaries = {t.assignment.primary for t in app.store.tasks_for_run(run_id) if t.assignment}
        assert len(primaries) >= 2
        app.close()


class TestFailureHandling:
    async def test_primary_failure_falls_back(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("feat", "FAKE:fail_if_agent:alpha\nFAKE:write:out.txt:done"),
                    assign("alpha", "beta", ["beta"]),
                )
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        attempts = app.store.attempts_for_task(app.store.tasks_for_run(run_id)[0].task_id)
        agents_tried = [a.agent for a in attempts if a.role == "primary"]
        assert agents_tried[0] == "alpha"
        assert "beta" in agents_tried  # fallback took over

    async def test_agent_unavailable_uses_fallback(self, tmp_path: Path) -> None:
        app = await make_project(
            tmp_path,
            ["broken"],
            extra_agents=agent_block("alpha") + "\n\n" + agent_block("beta"),
        )
        # "broken" is a fake agent whose executable does not exist.
        config_path = app.root / ".orkestra" / "config.toml"
        text = config_path.read_text().replace(
            '[agents.broken]\nadapter = "fake"',
            '[agents.broken]\nadapter = "external"\ncommand = ["/nonexistent-agent-xyz"]',
        )
        config_path.write_text(text)
        app.close()
        from orkestra.app import build_app

        app = build_app(app.root, offline=True)
        run_id = await manual_run(
            app,
            [
                (
                    spec("feat", "FAKE:write:out.txt:done"),
                    assign("broken", "alpha", ["beta"]),
                )
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        app.close()

    async def test_reviewer_rejection_then_repair(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("feat", "FAKE:reject_once\nFAKE:write:feature.txt:v1"),
                    assign("alpha", "beta"),
                )
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        task = app.store.tasks_for_run(run_id)[0]
        assert task.review_cycles == 1  # rejected once, then approved
        reviewer_attempts = [
            a for a in app.store.attempts_for_task(task.task_id) if a.role == "reviewer"
        ]
        assert len(reviewer_attempts) == 2

    async def test_deterministic_gate_vetoes_and_escalates(self, app: App) -> None:
        # `false` always exits 1: verification can never pass, an agent
        # claiming success is irrelevant, and the kernel escalates.
        run_id = await manual_run(
            app,
            [
                (
                    spec("doomed", "FAKE:write:x.txt:y", acceptance=["false"]),
                    assign("alpha", "beta", ["beta"]),
                )
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.WAITING_HUMAN
        task = app.store.tasks_for_run(run_id)[0]
        assert task.state is TaskState.BLOCKED
        decisions = app.store.decisions_for_run(run_id, unresolved_only=True)
        assert len(decisions) == 1
        assert "failed" in decisions[0].question

    async def test_decision_skip_then_run_fails_cleanly(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("doomed", "FAKE:write:x.txt:y", acceptance=["false"]),
                    assign("alpha", "beta", ["beta"]),
                )
            ],
        )
        await app.orchestrator.execute(run_id)
        [decision] = app.store.decisions_for_run(run_id, unresolved_only=True)
        message = app.orchestrator.apply_decision(decision.decision_id, "skip")
        assert "skipped" in message
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.FAILED

    async def test_decision_retry_resets_budgets(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("flaky", "FAKE:fail", acceptance=[]),
                    assign("alpha", "beta"),
                )
            ],
        )
        await app.orchestrator.execute(run_id)
        [decision] = app.store.decisions_for_run(run_id, unresolved_only=True)
        # Fix the task by resolving retry (fake still fails, but budgets reset
        # proves the loop re-enters; then cancel to end the test quickly).
        message = app.orchestrator.apply_decision(decision.decision_id, "retry")
        assert "reset" in message
        task = app.store.tasks_for_run(run_id)[0]
        assert task.state is TaskState.READY
        assert task.attempt_count == 0


class TestInterruptionAndResume:
    async def test_kill_and_resume_completes(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("slow", "FAKE:sleep:3\nFAKE:write:slow.txt:done"),
                    assign("alpha", "beta"),
                )
            ],
        )
        execution = asyncio.ensure_future(app.orchestrator.execute(run_id))
        await asyncio.sleep(1.2)
        execution.cancel()  # simulates process death mid-attempt
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert app.store.running_attempts(run_id)  # dangling attempt persisted
        await app.orchestrator.reconcile(run_id)
        assert not app.store.running_attempts(run_id)
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        files = await show_integration_files(app, run_id)
        assert "slow.txt" in files

    async def test_cancel_terminates_run(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (
                    spec("slow", "FAKE:sleep:20"),
                    assign("alpha", "beta"),
                )
            ],
        )
        execution = asyncio.ensure_future(app.orchestrator.execute(run_id))
        await asyncio.sleep(1.0)
        app.orchestrator.request_cancel(run_id)
        state = await asyncio.wait_for(execution, timeout=30)
        assert state is RunState.CANCELLED
        assert app.store.tasks_for_run(run_id)[0].state is TaskState.CANCELLED

    async def test_pause_then_resume(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (spec("a", "FAKE:write:a.txt:1"), assign("alpha", "beta")),
                (spec("b", "FAKE:write:b.txt:2", deps=["a"]), assign("beta", "alpha")),
            ],
        )
        app.orchestrator.request_pause(run_id)
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.PAUSED
        await app.orchestrator.reconcile(run_id)  # clears pause control
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE


class TestParallelism:
    async def test_independent_tasks_run_and_integrate(self, app: App) -> None:
        run_id = await manual_run(
            app,
            [
                (spec("left", "FAKE:write:left.txt:L"), assign("alpha", "beta")),
                (spec("right", "FAKE:write:right.txt:R"), assign("beta", "alpha")),
                (
                    spec("join", "FAKE:write:join.txt:J", deps=["left", "right"]),
                    assign("alpha", "beta"),
                ),
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        files = await show_integration_files(app, run_id)
        for name in ("left.txt", "right.txt", "join.txt"):
            assert name in files

    async def test_merge_conflict_recovery(self, app: App) -> None:
        # Two independent tasks writing the same file: second integration
        # conflicts, kernel recreates the workspace from the updated
        # integration branch and retries.
        run_id = await manual_run(
            app,
            [
                (spec("one", "FAKE:write:shared.txt:from-one"), assign("alpha", "beta")),
                (spec("two", "FAKE:write:shared.txt:from-two"), assign("beta", "alpha")),
            ],
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        files = await show_integration_files(app, run_id)
        assert "shared.txt" in files

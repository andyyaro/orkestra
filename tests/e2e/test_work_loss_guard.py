"""Work-loss guard: a task that reached INTEGRATING may never end DONE empty.

The scenario is built from real Git machinery, not mocks: two tasks touch
one file, the second one's merge genuinely conflicts, and its retry (a
fresh worktree off the moved integration head) produces no commit at all.
The assertions read the integration branch's *tree*, because every
state-shaped assertion in this situation is green while the diff is gone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orkestra.app import App
from orkestra.schemas.common import RunState, TaskKind, TaskState
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.workspace.git import GitRepo
from tests.e2e.conftest import agent_block, make_project

pytestmark = pytest.mark.e2e

WORKER = Path(__file__).parent / "conflict_worker.py"


async def make_conflict_project(tmp_path: Path) -> tuple[App, Path]:
    state = tmp_path / "worker-state"
    state.mkdir(parents=True, exist_ok=True)
    scripted = agent_block(
        "scripted",
        adapter="external",
        command=[sys.executable, str(WORKER), "--state-dir", str(state)],
    )
    app = await make_project(tmp_path, ["alpha", "beta"], concurrency=2, extra_agents=scripted)
    return app, state


def spec(key: str) -> TaskSpec:
    return TaskSpec(key=key, title=key, kind=TaskKind.IMPLEMENT, description=f"task {key}")


async def show(app: App, ref: str, path: str) -> str:
    code, out, _ = await GitRepo(app.root)._git("show", f"{ref}:{path}", check=False)
    return out if code == 0 else ""


async def refs_containing(app: App, needle: str, path: str) -> list[str]:
    """Every ref whose tip tree holds *path* with *needle* in its content."""
    _, listing, _ = await GitRepo(app.root)._git("for-each-ref", "--format=%(refname)")
    hits = []
    for ref in listing.split():
        if needle in await show(app, ref, path):
            hits.append(ref)
    return hits


async def test_integrating_task_with_no_commit_never_reports_done(tmp_path: Path) -> None:
    app, _state = await make_conflict_project(tmp_path)
    try:
        run_id = app.store.create_run(app.config.project.name)
        base, integration = await app.workspaces.start_run(run_id)
        app.store.set_run_git(run_id, base, integration)
        for key in ("first", "second"):
            app.store.add_task(
                run_id, spec(key), Assignment(primary="scripted", reviewers=["beta"])
            )

        run_state = await app.orchestrator.execute(run_id)

        tasks = {t.key: t for t in app.store.tasks_for_run(run_id)}
        events = app.store.events_for_run(run_id, limit=1000)
        conflicts = [e for e in events if "merge conflict integrating" in e["text"]]
        landed = await show(app, integration, "shared.txt")
        survivors = await refs_containing(app, "two", "shared.txt")

        # Print more state than the assertions need: this failure is silent.
        print(f"run state: {run_state.value}")
        print(f"task states: {[(k, t.state.value) for k, t in tasks.items()]}")
        print(f"merge-conflict events: {[e['text'] for e in conflicts]}")
        print(f"integration shared.txt: {landed!r}")
        print(f"refs still holding the second task's work: {survivors}")

        # Precondition: the second task really did reach INTEGRATING and lose
        # its merge. Without this the rest proves nothing.
        assert conflicts, "scenario did not produce a merge conflict"
        assert tasks["first"].state is TaskState.DONE
        assert "one" in landed, "the first task's work is missing from the integration tree"

        second = tasks["second"]
        if second.state is TaskState.DONE:
            # DONE is a claim about the tree, so the tree must back it up.
            assert "two" in landed, (
                "task 'second' is DONE but its work is absent from the integration "
                f"tree (shared.txt={landed!r}, surviving refs={survivors})"
            )
        else:
            assert second.state is TaskState.BLOCKED, second.state
            assert run_state is RunState.WAITING_HUMAN, run_state
            assert app.store.decisions_for_run(run_id, unresolved_only=True), (
                "blocked task left no decision for a human to resolve"
            )
    finally:
        app.close()


async def test_the_block_survives_the_remedy_it_recommends(tmp_path: Path) -> None:
    """Resolving with `retry` and resuming must not relaunder the falsehood.

    The first version of this guard armed itself from a local variable in
    `_run_task`. Taking its own recommended option and resuming therefore
    reproduced the defect on the next pass: run complete, task done, work on
    no ref. The condition is asked of Git now, so a fresh process gets the
    same answer.
    """
    app, _state = await make_conflict_project(tmp_path)
    try:
        run_id = app.store.create_run(app.config.project.name)
        base, integration = await app.workspaces.start_run(run_id)
        app.store.set_run_git(run_id, base, integration)
        for key in ("first", "second"):
            app.store.add_task(
                run_id, spec(key), Assignment(primary="scripted", reviewers=["beta"])
            )

        first_state = await app.orchestrator.execute(run_id)
        pending = app.store.decisions_for_run(run_id, unresolved_only=True)
        if first_state is not RunState.WAITING_HUMAN or not pending:
            landed = await show(app, integration, "shared.txt")
            assert "two" in landed, "no block was raised, so the work must have landed"
            return

        # Take the guard's own recommendation, then carry on as `resume` does.
        app.orchestrator.apply_decision(pending[0].decision_id, "retry")
        second_state = await app.orchestrator.execute(run_id)

        tasks = {t.key: t for t in app.store.tasks_for_run(run_id)}
        landed = await show(app, integration, "shared.txt")
        survivors = await refs_containing(app, "two", "shared.txt")
        print(f"after retry+resume: run={second_state.value}")
        print(f"task states: {[(k, t.state.value) for k, t in tasks.items()]}")
        print(f"integration shared.txt: {landed!r}; refs holding it: {survivors}")

        if tasks["second"].state is TaskState.DONE:
            assert "two" in landed, (
                "resume marked 'second' DONE while its work is absent from the "
                f"integration tree (shared.txt={landed!r}, refs={survivors})"
            )
        else:
            # Still blocked, or landed. Either is honest; vanishing is not.
            assert survivors or "two" in landed, "the second task's work vanished"
    finally:
        app.close()

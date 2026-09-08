"""An unbound gate is a config defect, and the run says so before spending.

The canary itself is tested in tests/unit/test_gate_binding.py against a
real editable-install reproduction. These tests check the wiring: that the
kernel asks the question once per run, before the first agent is
dispatched, and that a gate which cannot fail stops the run instead of
decorating it with a green tick.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from orkestra.app import App, build_app
from orkestra.schemas.common import RunState, TaskState
from orkestra.workspace.git import GitRepo
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec

PYTEST_GATE = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider tests"


async def _project_with_source(tmp_path: Path, commands: list[str], *, extra: str = "") -> App:
    """A real, tiny Python project whose gate is `commands`."""
    base = await make_project(tmp_path)
    root = base.root
    (root / "widget.py").write_text("VALUE = 41\n\n\ndef bump() -> int:\n    return VALUE + 1\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_widget.py").write_text(
        "from widget import bump\n\n\ndef test_bump() -> None:\n    assert bump() == 42\n"
    )
    rendered = ", ".join(f'"{c}"' for c in commands)
    config_path = root / ".orkestra" / "config.toml"
    config_path.write_text(
        config_path.read_text() + f"\n[verify]\ncommands = [{rendered}]{extra}\n"
    )
    await GitRepo(root).add_all_and_commit("add source and tests")
    base.close()
    return build_app(root, offline=True)


class TestUnboundGateStopsTheRun:
    async def test_vacuous_gate_blocks_before_any_agent_is_dispatched(self, tmp_path: Path) -> None:
        # `true` passes on every tree in the world, so it says nothing about
        # this one. Today that produced a confident green run.
        app = await _project_with_source(tmp_path, ["true"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            state = await app.orchestrator.execute(run_id)
            task = app.store.tasks_for_run(run_id)[0]
            events = app.store.events_for_run(run_id, limit=1000)
            texts = [str(e["text"]) for e in events]
            print("run state:", state, "task state:", task.state)
            print("attempts:", len(app.store.attempts_for_task(task.task_id)))
            for text in texts:
                if "binding" in text or "blocked" in text:
                    print("event:", text[:400])
            assert state is RunState.WAITING_HUMAN
            assert task.state is TaskState.BLOCKED
            assert any("gate binding UNBOUND" in text for text in texts)
            # No quota was spent: the gate was refused before dispatch.
            assert app.store.attempts_for_task(task.task_id) == []
            decisions = app.store.decisions_for_run(run_id, unresolved_only=True)
            assert decisions
            assert "editable" in decisions[0].plain
        finally:
            app.close()

    async def test_bound_gate_runs_normally_and_says_so_once(self, tmp_path: Path) -> None:
        app = await _project_with_source(tmp_path, [PYTEST_GATE])
        try:
            run_id = await manual_run(
                app,
                [
                    (spec("t1", "FAKE:write:a.txt:x"), assign("alpha", "beta")),
                    (spec("t2", "FAKE:write:b.txt:y"), assign("beta", "alpha")),
                ],
            )
            state = await app.orchestrator.execute(run_id)
            texts = [str(e["text"]) for e in app.store.events_for_run(run_id, limit=1000)]
            bound = [t for t in texts if t.startswith("gate binding")]
            print("binding events:", bound)
            print("run state:", state)
            assert state is RunState.COMPLETE
            # Exactly once per run, not once per task.
            assert len(bound) == 1
            assert "gate binding BOUND" in bound[0]
            assert "clean exit: 0" in bound[0]
        finally:
            app.close()

    async def test_binding_check_can_be_turned_off(self, tmp_path: Path) -> None:
        app = await _project_with_source(tmp_path, ["true"], extra="\nbinding_check = false")
        try:
            assert app.config.verify.binding_check is False
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            state = await app.orchestrator.execute(run_id)
            texts = [str(e["text"]) for e in app.store.events_for_run(run_id, limit=1000)]
            print("run state:", state)
            assert state is RunState.COMPLETE
            assert not [t for t in texts if t.startswith("gate binding")]
        finally:
            app.close()

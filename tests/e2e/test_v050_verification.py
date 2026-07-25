"""v0.5.0 kernel behavior: gate authority, no deterministic retry loops,
usage accounting, pause promptness, honest review reporting."""

from __future__ import annotations

from pathlib import Path

from orkestra.app import App
from orkestra.schemas.common import RunState, TaskState
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec


def _set_verify(app: App, commands: list[str]) -> App:
    """Rewrite the project's [verify] block and rebuild the app."""
    from orkestra.app import build_app

    config_path = app.root / ".orkestra" / "config.toml"
    text = config_path.read_text()
    rendered = ", ".join(f'"{c}"' for c in commands)
    config_path.write_text(text + f"\n[verify]\ncommands = [{rendered}]\n")
    app.close()
    return build_app(app.root, offline=True)


class TestGateAuthority:
    async def test_config_gate_runs_even_when_plan_supplies_acceptance(
        self, tmp_path: Path
    ) -> None:
        app = _set_verify(await make_project(tmp_path), ["false"])
        try:
            # The plan proposes a passing gate; the user's failing gate must
            # still run and veto — acceptance can add, never replace.
            run_id = await manual_run(
                app,
                [(spec("t", "FAKE:write:a.txt:x", acceptance=["true"]), assign("alpha", "beta"))],
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.WAITING_HUMAN
            assert app.store.tasks_for_run(run_id)[0].state is TaskState.BLOCKED
        finally:
            app.close()

    async def test_invalid_plan_acceptance_is_dropped_not_executed(self, tmp_path: Path) -> None:
        app = _set_verify(await make_project(tmp_path), ["true"])
        try:
            run_id = await manual_run(
                app,
                [
                    (
                        spec(
                            "t",
                            "FAKE:write:a.txt:x",
                            acceptance=["run the tests (they should pass)"],
                        ),
                        assign("alpha", "beta"),
                    )
                ],
            )
            state = await app.orchestrator.execute(run_id)
            # prose acceptance ignored; the real gate ("true") passes
            assert state is RunState.COMPLETE
            events = app.store.events_for_run(run_id, limit=1000)
            assert any("ignoring plan acceptance entry" in str(e["text"]) for e in events)
        finally:
            app.close()

    async def test_failure_output_is_captured_in_events(self, tmp_path: Path) -> None:
        from orkestra.workspace.git import GitRepo

        base = await make_project(tmp_path)
        # the gate script must be committed: verification runs inside the
        # task worktree, which only contains committed files
        (base.root / "gate.py").write_text(
            "import sys\nsys.stderr.write('BOOM-MARKER')\nsys.exit(1)\n"
        )
        await GitRepo(base.root).add_all_and_commit("add gate")
        app = _set_verify(base, ["python3 gate.py"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            events = app.store.events_for_run(run_id, limit=1000)
            assert any("BOOM-MARKER" in str(e["text"]) for e in events)
        finally:
            app.close()


class TestNoDeterministicRetryLoop:
    async def test_broken_gate_blocks_before_agent_runs(self, tmp_path: Path) -> None:
        app = _set_verify(await make_project(tmp_path), ["definitely-not-a-binary-xyz --go"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.WAITING_HUMAN
            task = app.store.tasks_for_run(run_id)[0]
            assert task.state is TaskState.BLOCKED
            # the agent was never dispatched: no attempts at all
            assert app.store.attempts_for_task(task.task_id) == []
            decision = app.store.decisions_for_run(run_id, unresolved_only=True)[0]
            assert "verification setup error" in decision.why_blocked
        finally:
            app.close()

    async def test_retry_without_fixing_config_does_not_replay_agent(self, tmp_path: Path) -> None:
        app = _set_verify(await make_project(tmp_path), ["definitely-not-a-binary-xyz --go"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            task = app.store.tasks_for_run(run_id)[0]
            decision = app.store.decisions_for_run(run_id, unresolved_only=True)[0]
            app.orchestrator.apply_decision(decision.decision_id, "retry")
            await app.orchestrator.execute(run_id)
            # still blocked, still zero agent attempts — no burned quota
            assert app.store.get_task(task.task_id).state is TaskState.BLOCKED
            assert app.store.attempts_for_task(task.task_id) == []
        finally:
            app.close()


class TestUsageAndReporting:
    async def test_probe_and_task_usage_recorded(self, tmp_path: Path) -> None:
        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            usage = app.store.usage_summary(run_id)
            assert usage, "task execution must be billed"
            assert all("cached_input_tokens" in row for row in usage)
        finally:
            app.close()

    async def test_report_counts_survive_human_retry(self, tmp_path: Path) -> None:
        from orkestra.report.final import build_report

        app = _set_verify(await make_project(tmp_path), ["false"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            task = app.store.tasks_for_run(run_id)[0]
            before = len(app.store.attempts_for_task(task.task_id))
            decision = app.store.decisions_for_run(run_id, unresolved_only=True)[0]
            app.orchestrator.apply_decision(decision.decision_id, "retry")
            # task counters were reset by 'retry'…
            assert app.store.get_task(task.task_id).attempt_count == 0
            # …but the report reflects real history from attempt rows
            report = build_report(app.store, run_id)
            assert report["tasks"][0]["attempt_count"] == before > 0
        finally:
            app.close()

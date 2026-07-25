"""v0.5.2: agents told the truth about their sandbox, honest counts,
liveness, and cheaper planning for small specs."""

from __future__ import annotations

from pathlib import Path

from orkestra.app import build_app
from orkestra.schemas.common import RunState, TaskKind
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec


class TestBriefTellsAgentTheTruth:
    async def test_default_brief_forbids_asking_for_command_approval(self, tmp_path: Path) -> None:
        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            task = app.store.tasks_for_run(run_id)[0]
            brief = app.orchestrator._render_brief(task, "", agent_name="alpha")
            assert "CANNOT run shell commands" in brief
            assert "do not ask" in brief
            assert "runs the acceptance commands for you" in brief
        finally:
            app.close()

    async def test_run_commands_agent_is_invited_to_self_check(self, tmp_path: Path) -> None:
        app = await make_project(tmp_path)
        config = app.root / ".orkestra" / "config.toml"
        config.write_text(
            config.read_text().replace(
                '[agents.alpha]\nadapter = "fake"',
                '[agents.alpha]\nadapter = "fake"\nrun_commands = true',
            )
        )
        app.close()
        app = build_app(app.root, offline=True)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            task = app.store.tasks_for_run(run_id)[0]
            brief = app.orchestrator._render_brief(task, "", agent_name="alpha")
            assert "You MAY run commands" in brief
            # the other agent keeps the default
            assert "CANNOT run shell commands" in app.orchestrator._render_brief(
                task, "", agent_name="beta"
            )
        finally:
            app.close()

    def test_claude_adapter_passes_allowed_tools_only_when_opted_in(self) -> None:
        from orkestra.adapters.claude_code import ClaudeCodeAdapter
        from orkestra.schemas.task import TaskBrief

        brief = TaskBrief(
            task_id="t",
            run_id="r",
            title="t",
            kind=TaskKind.IMPLEMENT,
            instructions="do it",
            cwd="/tmp",
            timeout_s=60,
        )
        default = ClaudeCodeAdapter().build_invocation(brief).argv
        assert "--allowedTools" not in default
        opted = ClaudeCodeAdapter(run_commands=True).build_invocation(brief).argv
        assert "--allowedTools" in opted
        assert opted[opted.index("--allowedTools") + 1] == "Bash"


class TestHonestSummaries:
    async def test_skipped_reviews_and_dropped_checks_are_counted(self, tmp_path: Path) -> None:
        from orkestra.cli.main import _gather_run_summary

        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app,
                [
                    (
                        spec(
                            "r",
                            "FAKE:write:NOTES.md:hi",
                            kind=TaskKind.RESEARCH,
                            acceptance=["run the tests (they should pass)"],
                        ),
                        assign("alpha", "beta"),
                    )
                ],
            )
            assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
            summary = await _gather_run_summary(app, run_id)
            assert summary.reviews_skipped >= 1
            assert summary.dropped_checks >= 1
        finally:
            app.close()

    async def test_json_report_has_usage_total(self, tmp_path: Path) -> None:
        from orkestra.report.final import build_report

        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            report = build_report(app.store, run_id)
            total = report["usage_total"]
            assert total["calls"] == sum(r["calls"] for r in report["usage"])
            assert "agents_reporting_cost" in total
        finally:
            app.close()


class TestSmallPlansAreCheap:
    async def test_challenger_count_scales_with_plan_size(self, tmp_path: Path) -> None:
        """A one- or two-task plan gets one challenge round, not two."""
        from orkestra.kernel.prepare import prepare_run

        app = await make_project(tmp_path, ["alpha", "beta", "gamma"])
        try:
            (app.root / "SPEC.md").write_text("# Tiny\nAdd one helper function.\n")
            run_id = await prepare_run(
                app.orchestrator, app.director, "# Tiny\nAdd one helper function.\n"
            )
            tasks = app.store.tasks_for_run(run_id)
            events = app.store.events_for_run(run_id, limit=1000)
            texts = " ".join(str(e["text"]) for e in events)
            if len(tasks) <= 2:
                assert "to keep planning cheap" in texts
        finally:
            app.close()

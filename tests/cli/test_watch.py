"""TUI tests via Textual's Pilot harness (fake agents, completed run)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

textual = pytest.importorskip("textual")

from typer.testing import CliRunner  # noqa: E402

from orkestra.app import build_app  # noqa: E402
from orkestra.cli.main import app as cli_app  # noqa: E402
from orkestra.cli.watch import WatchApp  # noqa: E402
from tests.cli.test_cli import FAKE_CONFIG  # noqa: E402

runner = CliRunner()


@pytest.fixture
def finished_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_app, ["init", str(root), "--non-interactive"])
    assert result.exit_code == 0, result.output
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# TUI Demo\nBuild a widget.\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "spec"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(root)
    result = runner.invoke(cli_app, ["run", "--offline"])
    assert result.exit_code == 0, result.output
    return root


class TestWatchApp:
    async def test_renders_run_summary_tasks_and_events(self, finished_project: Path) -> None:
        application = build_app(finished_project)
        run = application.store.latest_run()
        assert run is not None
        watch = WatchApp(application, run.run_id)
        async with watch.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import DataTable, RichLog, Static

            summary = watch.query_one("#summary", Static)
            summary_text = str(summary.render())
            assert run.run_id in summary_text
            assert "complete" in summary_text
            table = watch.query_one("#tasks", DataTable)
            assert table.row_count == 3  # implement / test / document
            log = watch.query_one("#events", RichLog)
            assert len(log.lines) > 0
        application.close()

    async def test_pause_key_sets_control_flag(self, finished_project: Path) -> None:
        application = build_app(finished_project)
        run = application.store.latest_run()
        assert run is not None
        watch = WatchApp(application, run.run_id)
        async with watch.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()
        refreshed = application.store.get_run(run.run_id)
        assert refreshed.payload.get("control") == "pause"
        application.close()

    def test_cli_watch_without_runs_fails_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "empty"
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli_app, ["init", str(root), "--non-interactive"])
        assert result.exit_code == 0
        (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
        monkeypatch.chdir(root)
        result = runner.invoke(cli_app, ["watch"])
        assert result.exit_code == 1
        assert "no runs found" in result.output

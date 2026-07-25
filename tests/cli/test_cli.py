"""CLI tests via Typer's runner (fake agents, offline director)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app


def git_commit_all(root: Path, message: str = "test setup") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


runner = CliRunner()

FAKE_CONFIG = """
version = 1

[project]
name = "cli-demo"

[agents.alpha]
adapter = "fake"

[agents.beta]
adapter = "fake"

[director]
agent = "alpha"

[probes]
mode = "off"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", str(root), "--non-interactive"])
    assert result.exit_code == 0, result.output
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# CLI Demo\nBuild a widget.\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    return root


class TestBasics:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "orkestra" in result.output

    def test_help_lists_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in (
            "init",
            "doctor",
            "run",
            "status",
            "decisions",
            "approve",
            "pause",
            "resume",
            "cancel",
            "report",
        ):
            assert command in result.output

    def test_commands_outside_project_fail_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "no Orkestra project" in result.output


class TestInit:
    def test_init_creates_layout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "newproj", "--non-interactive"])
        assert result.exit_code == 0, result.output
        root = tmp_path / "newproj"
        assert (root / ".orkestra" / "config.toml").exists()
        assert (root / "SPEC.md").exists()
        assert ".orkestra/" in (root / ".gitignore").read_text()
        assert (root / ".git").exists()

    def test_init_refuses_overwrite(self, project: Path) -> None:
        result = runner.invoke(app, ["init", str(project), "--non-interactive"])
        assert result.exit_code == 1
        assert "refusing to overwrite" in result.output


class TestDoctorAndAgents:
    def test_doctor_with_fake_agents(self, project: Path) -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "agents ready" in result.output

    def test_agents_list(self, project: Path) -> None:
        result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        assert "alpha" in result.output and "beta" in result.output


class TestWorkflow:
    def test_plan_run_status_logs_report(self, project: Path) -> None:
        result = runner.invoke(app, ["plan", "--offline"])
        assert result.exit_code == 0, result.output
        assert "plan ready" in result.output

        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 0, result.output
        assert "Run complete" in result.output
        assert "orkestra review" in result.output  # journey guidance
        assert "ork/run_" not in result.output.split("Run complete")[1]

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "complete" in result.output

        result = runner.invoke(app, ["logs", "--limit", "20"])
        assert result.exit_code == 0

        result = runner.invoke(app, ["decisions"])
        assert result.exit_code == 0
        assert "no open decisions" in result.output

        report_path = project / "report.md"
        json_path = project / "report.json"
        result = runner.invoke(
            app, ["report", "--out", str(report_path), "--json-out", str(json_path)]
        )
        assert result.exit_code == 0
        assert "Orkestra Run Report" in report_path.read_text()
        assert json.loads(json_path.read_text())["run"]["state"] == "complete"

    def test_status_json(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0

    def test_analyze_offline(self, project: Path) -> None:
        result = runner.invoke(app, ["analyze", "--offline"])
        assert result.exit_code == 0, result.output
        assert "Summary:" in result.output

    def test_missing_spec_error(self, project: Path) -> None:
        (project / "SPEC.md").unlink()
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 1
        assert "specification file not found" in result.output


class TestDecisionFlow:
    def test_blocked_run_decision_approve_resume(self, project: Path) -> None:
        # A spec whose implement task always fails leads to a human decision.
        (project / "SPEC.md").write_text("# Doomed\nFAKE:fail:always\n")
        git_commit_all(project)
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 2, result.output  # waiting on human
        result = runner.invoke(app, ["decisions"])
        assert "--option" in result.output
        assert "what this means" in result.output
        decision_id = next(
            line.strip().split()[0]
            for line in result.output.splitlines()
            if line.strip().startswith("dec_")
        )
        result = runner.invoke(app, ["approve", decision_id, "--option", "skip"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["approve", decision_id, "--option", "skip"])
        assert result.exit_code == 1  # double resolve rejected

    def test_approve_unknown_decision(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        result = runner.invoke(app, ["approve", "dec_missing", "--option", "x"])
        assert result.exit_code == 1

    def test_pause_and_cancel_flags(self, project: Path) -> None:
        # active (waiting on a human) run: pause/cancel are legitimate
        (project / "SPEC.md").write_text("# Doomed\nFAKE:fail:always\n")
        git_commit_all(project)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 2
        assert runner.invoke(app, ["pause"]).exit_code == 0
        assert runner.invoke(app, ["cancel"]).exit_code == 0
        # a finished run has nothing to pause or cancel
        (project / "SPEC.md").write_text("# Fine\nBuild a widget.\n")
        git_commit_all(project)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
        assert runner.invoke(app, ["pause"]).exit_code == 1
        assert runner.invoke(app, ["cancel"]).exit_code == 1


class TestDiffMerge:
    """Backward-compatible aliases share the review/accept implementation."""

    def test_diff_alias_matches_review(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        review_output = runner.invoke(app, ["review"]).output
        diff_output = runner.invoke(app, ["diff"]).output
        assert review_output == diff_output
        result = runner.invoke(app, ["diff", "--full"])
        assert result.exit_code == 0
        assert "diff --git" in result.output

    def test_merge_alias_accepts_with_yes(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        result = runner.invoke(app, ["merge", "--cleanup", "--yes"])
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output
        markers = list(project.glob("fake-task_*.txt"))
        assert markers, "accepted results should be in the working tree"
        assert "tidied up" in result.output
        branches = subprocess.run(
            ["git", "branch", "--list", "ork/*"],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert branches == ""

    def test_merge_refuses_dirty_tree(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        (project / "SPEC.md").write_text("modified after run\n")
        result = runner.invoke(app, ["merge", "--yes"])
        assert result.exit_code == 1
        assert "uncommitted changes" in result.output
        assert "git stash" in result.output

    def test_diff_without_results(self, project: Path) -> None:
        result = runner.invoke(app, ["diff"])
        assert result.exit_code == 1
        assert "no runs found" in result.output


class TestDemo:
    def test_demo_full_lifecycle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["demo", "--path", str(tmp_path / "d")])
        assert result.exit_code == 0, result.output
        out = result.output
        assert "review rejection triggered a repair loop" in out
        assert "changes requested" in out  # the rejection happened
        assert "feature_a.py" in out and "feature_b.py" in out
        assert ".fake-reject-done" not in out  # internals stay hidden
        assert "orkestra start" in out  # points to the next step


class TestApproveInteractive:
    def test_no_args_single_decision_prompted(self, project: Path) -> None:
        (project / "SPEC.md").write_text("# Doomed\nFAKE:fail:always\n")
        git_commit_all(project)
        runner.invoke(app, ["run", "--offline"])
        # No id, no --option: picks the only decision, prompts, default=retry
        result = runner.invoke(app, ["approve"], input="\n")
        assert result.exit_code == 0, result.output
        assert "what this means" in result.output
        assert "reset" in result.output  # retry applied

    def test_no_open_decisions(self, project: Path) -> None:
        runner.invoke(app, ["run", "--offline"])
        result = runner.invoke(app, ["approve"])
        assert result.exit_code == 1
        assert "no open decisions" in result.output


class TestRunWatchGuards:
    def test_watch_requires_tty(self, project: Path) -> None:
        result = runner.invoke(app, ["run", "--offline", "--watch"])
        assert result.exit_code == 1
        assert "interactive terminal" in result.output


class TestAgentsSetModels:
    def test_set_model_and_effort_preserves_comments(self, project: Path) -> None:
        config = project / ".orkestra" / "config.toml"
        config.write_text("# my precious comment\n" + config.read_text())
        result = runner.invoke(
            app, ["agents", "set", "alpha", "--model", "sonnet", "--effort", "high"]
        )
        assert result.exit_code == 0, result.output
        text = config.read_text()
        assert "# my precious comment" in text
        assert 'model = "sonnet"' in text
        assert 'effort = "high"' in text

    def test_invalid_effort_rolls_back(self, project: Path) -> None:
        config = project / ".orkestra" / "config.toml"
        before = config.read_text()
        result = runner.invoke(app, ["agents", "set", "alpha", "--effort", "extreme"])
        assert result.exit_code == 1
        assert "rolled back" in result.output
        assert config.read_text() == before

    def test_unknown_agent(self, project: Path) -> None:
        result = runner.invoke(app, ["agents", "set", "ghost", "--model", "x"])
        assert result.exit_code == 1
        assert "no agent named" in result.output

    def test_clear(self, project: Path) -> None:
        runner.invoke(app, ["agents", "set", "alpha", "--model", "sonnet"])
        result = runner.invoke(app, ["agents", "set", "alpha", "--clear"])
        assert result.exit_code == 0
        assert 'model = "sonnet"' not in (project / ".orkestra" / "config.toml").read_text()

    def test_models_listing(self, project: Path) -> None:
        result = runner.invoke(app, ["agents", "models"])
        assert result.exit_code == 0
        assert "alpha" in result.output

    def test_list_shows_model_and_effort(self, project: Path) -> None:
        runner.invoke(app, ["agents", "set", "alpha", "--model", "sonnet", "--effort", "low"])
        result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        assert "sonnet" in result.output and "low" in result.output

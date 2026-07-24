"""CLI tests via Typer's runner (fake agents, offline director)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner


def git_commit_all(root: Path, message: str = "test setup") -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "commit", "-q", "--allow-empty", "-m", message],
        cwd=root, check=True, capture_output=True,
    )

from orkestra.cli.main import app

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
        for command in ("init", "doctor", "run", "status", "decisions", "approve",
                        "pause", "resume", "cancel", "report"):
            assert command in result.output

    def test_commands_outside_project_fail_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        assert "no Orkestra project" in result.output


class TestInit:
    def test_init_creates_layout(self, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert "run complete" in result.output

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
        result = runner.invoke(app, ["report", "--out", str(report_path),
                                     "--json-out", str(json_path)])
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
        runner.invoke(app, ["run", "--offline"])
        assert runner.invoke(app, ["pause"]).exit_code == 0
        assert runner.invoke(app, ["cancel"]).exit_code == 0

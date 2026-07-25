"""v0.4.4: never set up a project inside a subdirectory of another repo,
and validate --agents before any mutation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.test_cli import git_commit_all
from tests.cli.test_start_journey import mock_detection

runner = CliRunner()


def _parent_repo(tmp_path: Path) -> Path:
    parent = tmp_path / "bigrepo"
    (parent / "sub").mkdir(parents=True)
    (parent / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "init", "-q"], cwd=parent, check=True, capture_output=True)
    git_commit_all(parent)
    return parent


def _git_status(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout


class TestNestedRepoGuard:
    def test_start_in_subdir_refuses_without_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        parent = _parent_repo(tmp_path)
        sub = parent / "sub"
        before = _git_status(parent)
        result = runner.invoke(app, ["start", str(sub), "--non-interactive", "--no-run"])
        assert result.exit_code == 1, result.output
        flat = " ".join(result.output.split())
        assert "inside an existing Git repository" in flat
        assert parent.name in flat  # tells the user where the repo root is
        assert not (sub / ".orkestra").exists()
        assert not (sub / ".gitignore").exists()
        assert not (sub / "SPEC.md").exists()
        assert _git_status(parent) == before

    def test_init_in_subdir_refuses_without_mutation(self, tmp_path: Path) -> None:
        parent = _parent_repo(tmp_path)
        sub = parent / "sub"
        before = _git_status(parent)
        result = runner.invoke(app, ["init", str(sub), "--non-interactive"])
        assert result.exit_code == 1, result.output
        assert "inside an existing Git repository" in " ".join(result.output.split())
        assert not (sub / ".orkestra").exists()
        assert _git_status(parent) == before

    def test_start_at_repo_root_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        parent = _parent_repo(tmp_path)
        result = runner.invoke(app, ["start", str(parent), "--non-interactive", "--no-run"])
        assert result.exit_code == 0, result.output
        assert (parent / ".orkestra" / "config.toml").exists()


class TestAgentsValidatedBeforeMutation:
    def test_bad_agents_value_leaves_directory_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        target = tmp_path / "fresh"
        result = runner.invoke(
            app,
            ["start", str(target), "--non-interactive", "--agents", "claude,cursor"],
        )
        assert result.exit_code == 1
        assert "unknown agent name" in " ".join(result.output.split())
        # validation must run before repo init / any file writes
        assert not (target / ".git").exists()
        assert not (target / ".gitignore").exists()
        assert not (target / ".orkestra").exists()

    def test_single_agent_value_leaves_directory_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        target = tmp_path / "fresh2"
        result = runner.invoke(
            app,
            ["start", str(target), "--non-interactive", "--agents", "claude"],
        )
        assert result.exit_code == 1
        assert not (target / ".git").exists()

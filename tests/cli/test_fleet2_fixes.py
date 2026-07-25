"""Regressions for the fleet-#2 findings (fixed in v0.4.5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.test_cli import FAKE_CONFIG, git_commit_all
from tests.cli.test_start_journey import mock_detection

runner = CliRunner()


def _practice_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    return root


class TestAgentsZeroMutation:
    def test_not_signed_in_leaves_directory_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # claude ready, codex present-but-not-signed-in: refusal must
        # happen BEFORE the repo/.gitignore are created.
        mock_detection(monkeypatch, {"claude-code": True, "codex-cli": False})
        target = tmp_path / "fresh"
        result = runner.invoke(
            app,
            ["start", str(target), "--non-interactive", "--agents", "claude,codex"],
        )
        assert result.exit_code == 1, result.output
        assert "not signed in" in " ".join(result.output.split())
        assert not (target / ".git").exists()
        assert not (target / ".gitignore").exists()
        assert not (target / ".orkestra").exists()

    def test_empty_agents_value_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        target = tmp_path / "empty"
        result = runner.invoke(app, ["start", str(target), "--non-interactive", "--agents", ""])
        assert result.exit_code == 1
        assert "at least two" in " ".join(result.output.split())
        assert not (target / ".git").exists()


class TestNestedProjectGuardEverywhere:
    def test_status_refuses_stray_nested_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        parent = tmp_path / "bigrepo"
        sub = parent / "stray"
        (sub / ".orkestra").mkdir(parents=True)
        (parent / "app.py").write_text("print('hi')\n")
        subprocess.run(["git", "init", "-q"], cwd=parent, check=True, capture_output=True)
        git_commit_all(parent)
        (sub / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
        monkeypatch.chdir(sub)
        for argv in (["status"], ["doctor"], ["run", "--offline"]):
            result = runner.invoke(app, argv)
            assert result.exit_code == 1, (argv, result.output)
            assert "inside another Git repository" in " ".join(result.output.split()), argv

    def test_project_at_repo_root_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0


class TestReportFixes:
    def test_out_creates_missing_parent_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
        result = runner.invoke(app, ["report", "--out", str(root / "deep" / "sub" / "r.md")])
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output
        assert (root / "deep" / "sub" / "r.md").exists()

    def test_agents_section_populated_after_offline_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        flat = " ".join(result.output.split())
        assert "alpha" in flat and "beta" in flat  # FAKE_CONFIG agent names

    def test_demo_report_agents_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(app, ["demo", "--path", str(tmp_path / "d")]).exit_code == 0
        monkeypatch.chdir(tmp_path / "d")
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        flat = " ".join(result.output.split())
        assert "ada" in flat and "grace" in flat


class TestPracticeHeadline:
    def test_practice_run_headline_is_honest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _practice_project(tmp_path, monkeypatch)
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "Practice run complete" in flat
        assert "verified result is ready" not in flat
        assert "practice run:" in flat

    def test_accept_preflight_shows_practice_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
        result = runner.invoke(app, ["accept"], input="\n")
        assert "practice run:" in " ".join(result.output.split())
        assert "nothing changed" in result.output


class TestCancelledExitCode:
    def test_cancelled_run_exits_3(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["plan", "--offline"]).exit_code == 0
        assert runner.invoke(app, ["cancel"]).exit_code == 0
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 3, result.output


class TestPlainLanguageErrors:
    def test_invalid_effort_says_must_be_one_of(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _practice_project(tmp_path, monkeypatch)
        config = (root / ".orkestra" / "config.toml").read_text()
        (root / ".orkestra" / "config.toml").write_text(
            config.replace(
                '[agents.beta]\nadapter = "fake"',
                '[agents.beta]\nadapter = "fake"\neffort = "ultra"',
            )
        )
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1
        flat = " ".join(result.output.split())
        assert "must be one of" in flat
        assert "Input should be" not in flat

    def test_unreadable_orkestra_dir_fails_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _practice_project(tmp_path, monkeypatch)
        assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
        (root / ".orkestra").chmod(0o500)
        try:
            result = runner.invoke(app, ["status"])
            assert "Traceback" not in result.output
        finally:
            (root / ".orkestra").chmod(0o700)


class TestProjectNameSlug:
    def test_non_ascii_directory_name_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "mon projet émoji"
        result = runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run"])
        assert result.exit_code == 0, result.output
        from orkestra.schemas.config import load_config

        config = load_config(root / ".orkestra" / "config.toml")
        assert config.project.name  # valid slug, loads cleanly

    def test_slugify_unit(self) -> None:
        from orkestra.cli.start import _slugify_project_name

        assert _slugify_project_name("Mon Projet Émoji") == "mon-projet-moji"
        assert _slugify_project_name("---") == "project"
        assert _slugify_project_name("普通话") == "project"
        assert _slugify_project_name("My.App_2") == "my.app_2"


class TestGitignoreSeeding:
    def test_python_project_gets_pycache_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "pyproj"
        root.mkdir()
        (root / "main.py").write_text("print('x')\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        git_commit_all(root)
        result = runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run"])
        assert result.exit_code == 0, result.output
        ignore = (root / ".gitignore").read_text()
        assert "__pycache__/" in ignore
        assert ".orkestra/" in ignore


class TestDoctorPreInit:
    def test_doctor_without_project_checks_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        flat = " ".join(result.output.split())
        assert "checking the environment only" in flat
        assert "git:" in flat
        assert "Traceback" not in result.output

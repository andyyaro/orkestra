"""v0.4.3: --agents restriction, report --save location, practice-mode honesty."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.test_cli import FAKE_CONFIG, git_commit_all
from tests.cli.test_start_journey import mock_detection

runner = CliRunner()

ALL_READY = {"claude-code": True, "codex-cli": True, "antigravity-cli": True}


def _finished_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
    return root


class TestAgentsFlag:
    def test_restricts_enabled_agents(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from orkestra.schemas.config import load_config

        mock_detection(monkeypatch, ALL_READY)
        root = tmp_path / "picked"
        result = runner.invoke(
            app,
            ["start", str(root), "--non-interactive", "--no-run", "--agents", "claude,codex"],
        )
        assert result.exit_code == 0, result.output
        assert "using only: claude-code, codex-cli" in result.output.replace("\n", " ")
        config = load_config(root / ".orkestra" / "config.toml")
        adapters = {a.adapter for a in config.agents.values() if a.enabled}
        assert "antigravity-cli" not in adapters
        assert {"claude-code", "codex-cli"} <= adapters

    def test_aliases_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_detection(monkeypatch, ALL_READY)
        result = runner.invoke(
            app,
            [
                "start",
                str(tmp_path / "alias"),
                "--non-interactive",
                "--no-run",
                "--agents",
                "claude-code, agy",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "using only: claude-code, antigravity-cli" in result.output.replace("\n", " ")

    def test_unknown_name_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_detection(monkeypatch, ALL_READY)
        result = runner.invoke(
            app,
            ["start", str(tmp_path / "x"), "--non-interactive", "--agents", "claude,cursor"],
        )
        assert result.exit_code == 1
        flat = " ".join(result.output.split())
        assert "unknown agent name" in flat
        assert "cursor" in flat

    def test_single_agent_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_detection(monkeypatch, ALL_READY)
        result = runner.invoke(
            app,
            ["start", str(tmp_path / "x"), "--non-interactive", "--agents", "claude"],
        )
        assert result.exit_code == 1
        assert "at least two" in " ".join(result.output.split())

    def test_requested_but_not_signed_in_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {"claude-code": True, "codex-cli": False})
        result = runner.invoke(
            app,
            ["start", str(tmp_path / "x"), "--non-interactive", "--agents", "claude,codex"],
        )
        assert result.exit_code == 1
        flat = " ".join(result.output.split())
        assert "not signed in" in flat
        assert "codex-cli" in flat
        # must NOT silently fall back to practice mode
        assert "practice mode" not in flat


class TestReportLocation:
    def test_save_writes_under_orkestra_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _finished_project(tmp_path, monkeypatch)
        result = runner.invoke(app, ["report", "--save"])
        assert result.exit_code == 0, result.output
        reports = list((root / ".orkestra" / "reports").iterdir())
        suffixes = sorted(p.suffix for p in reports)
        assert suffixes == [".json", ".md"]
        assert "untracked" not in result.output

    def test_out_in_repo_root_warns_untracked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _finished_project(tmp_path, monkeypatch)
        result = runner.invoke(app, ["report", "--out", str(root / "report.md")])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "untracked" in flat
        assert "--save" in flat
        assert (root / "report.md").exists()

    def test_out_outside_repo_no_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finished_project(tmp_path, monkeypatch)
        target = tmp_path / "elsewhere.md"
        result = runner.invoke(app, ["report", "--out", str(target)])
        assert result.exit_code == 0, result.output
        assert "untracked" not in result.output
        assert target.exists()


class TestPracticeModeHonesty:
    def test_run_completion_mentions_practice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "proj"
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
        (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
        (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
        git_commit_all(root)
        monkeypatch.chdir(root)
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())
        assert "practice run:" in flat
        assert "SPEC.md is not actually implemented" in flat

    def test_review_mentions_practice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _finished_project(tmp_path, monkeypatch)
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 0, result.output
        assert "practice run:" in " ".join(result.output.split())

    def test_helper_false_for_real_adapters(self) -> None:
        from types import SimpleNamespace

        from orkestra.cli.main import _is_practice_mode

        fake = SimpleNamespace(adapter="fake")
        real = SimpleNamespace(adapter="claude-code")
        app_all_fake = SimpleNamespace(
            config=SimpleNamespace(enabled_agents={"a": fake, "b": fake})
        )
        app_mixed = SimpleNamespace(config=SimpleNamespace(enabled_agents={"a": fake, "b": real}))
        assert _is_practice_mode(app_all_fake) is True  # type: ignore[arg-type]
        assert _is_practice_mode(app_mixed) is False  # type: ignore[arg-type]

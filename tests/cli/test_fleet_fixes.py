"""Regressions for the v0.4.1 fleet-test findings (fixed in v0.4.2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.test_cli import FAKE_CONFIG, git_commit_all
from tests.cli.test_start_journey import mock_detection

runner = CliRunner()

VERIFIED_CONFIG = FAKE_CONFIG + '\n[verify]\ncommands = ["true"]\n'


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: str) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
    (root / ".orkestra" / "config.toml").write_text(config)
    (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def finished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _project(tmp_path, monkeypatch, FAKE_CONFIG)
    assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
    return root


class TestMessageRendering:
    """Rich markup was eating [verify] and [tui] out of user-facing text."""

    def test_init_message_renders_verify_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", str(tmp_path / "p"), "--non-interactive"])
        assert result.exit_code == 0
        assert "[verify] in .orkestra/config.toml" in result.output
        assert "add your own to  in" not in result.output

    def test_watch_help_names_the_extra(self) -> None:
        result = runner.invoke(app, ["watch", "--help"])
        assert result.exit_code == 0
        assert "'tui' extra" in result.output
        assert "the  extra" not in result.output


class TestVerificationHonesty:
    """Never claim 'verification passed' when nothing was configured."""

    def test_run_and_review_say_skipped_without_commands(self, finished: Path) -> None:
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 0, result.output
        assert "no test commands configured" in result.output
        assert "passed your" not in result.output

    def test_run_and_review_say_passed_with_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(tmp_path, monkeypatch, VERIFIED_CONFIG)
        run_result = runner.invoke(app, ["run", "--offline"])
        assert run_result.exit_code == 0, run_result.output
        assert "verification: passed (your test commands" in run_result.output
        review = runner.invoke(app, ["review"])
        assert "passed your test" in review.output
        assert "no test commands configured" not in review.output

    def test_accept_preflight_reflects_missing_commands(self, finished: Path) -> None:
        result = runner.invoke(app, ["accept"], input="\n")
        assert "verification: none configured" in result.output


class TestAcceptIdempotence:
    def test_second_accept_is_a_friendly_noop(self, finished: Path) -> None:
        first = runner.invoke(app, ["accept", "--yes"])
        assert first.exit_code == 0, first.output
        assert "✓ accepted" in first.output
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=finished, capture_output=True, text=True
        ).stdout
        second = runner.invoke(app, ["accept", "--yes"])
        assert second.exit_code == 0, second.output
        assert "already part of" in second.output
        assert "✓ accepted" not in second.output
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=finished, capture_output=True, text=True
        ).stdout
        assert head == head_after

    def test_accept_after_cleanup_no_traceback(self, finished: Path) -> None:
        first = runner.invoke(app, ["accept", "--yes", "--cleanup"])
        assert first.exit_code == 0, first.output
        second = runner.invoke(app, ["accept", "--yes"])
        assert second.exit_code == 0, second.output
        assert "already part of" in second.output
        assert "Traceback" not in second.output

    def test_deleted_branch_without_acceptance_fails_plainly(self, finished: Path) -> None:
        branches = subprocess.run(
            ["git", "branch", "--list", "ork/*/integration", "--format=%(refname:short)"],
            cwd=finished,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert branches
        subprocess.run(["git", "branch", "-D", branches[0]], cwd=finished, check=True)
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 1
        assert "no longer available" in result.output
        assert "Traceback" not in result.output

    def test_confirm_eof_gives_yes_guidance(self, finished: Path) -> None:
        # stdin ends before the y/N question is answered (CI, redirected input)
        result = runner.invoke(app, ["accept"], input="")
        assert result.exit_code == 1
        assert "--yes" in result.output
        assert "Traceback" not in result.output


class TestBadRunIds:
    """--run with an unknown id must fail with error:, never a traceback."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["status", "--run", "run_nope", "--json"],
            ["report", "--run", "run_nope"],
            ["logs", "--run", "run_nope"],
            ["review", "--run", "run_nope"],
            ["cancel", "--run", "run_nope"],
        ],
    )
    def test_unknown_run_id(self, finished: Path, argv: list[str]) -> None:
        result = runner.invoke(app, argv)
        assert result.exit_code == 1, result.output
        assert "not found" in result.output
        assert "Traceback" not in result.output


class TestControlOnFinishedRuns:
    def test_cancel_completed_run_refuses(self, finished: Path) -> None:
        result = runner.invoke(app, ["cancel"])
        assert result.exit_code == 1
        assert "already finished" in result.output
        assert "cancel requested" not in result.output

    def test_pause_completed_run_refuses(self, finished: Path) -> None:
        result = runner.invoke(app, ["pause"])
        assert result.exit_code == 1
        assert "already finished" in result.output


class TestStartWizard:
    def test_custom_preset_non_interactive_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        result = runner.invoke(
            app,
            ["start", str(tmp_path / "c"), "--non-interactive", "--preset", "custom", "--no-run"],
        )
        assert result.exit_code == 1
        assert "interactive" in result.output
        assert "balanced" in result.output  # points at usable alternatives

    def test_blank_spec_answers_get_guidance_then_clean_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        # preset choice, verify skip, then only blank lines until EOF
        result = runner.invoke(app, ["start", str(tmp_path / "w")], input="1\n\n\n\n\n")
        assert result.exit_code == 1
        assert "can't be blank" in result.output.replace("\n", " ")
        assert "input ended" in result.output
        assert "--non-interactive" in result.output

    def test_valid_wizard_input_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "ok"
        result = runner.invoke(
            app,
            ["start", str(root)],
            input="1\n\nadd a greeting module\n\n\nn\n",
        )
        assert result.exit_code == 0, result.output
        assert "add a greeting module" in (root / "SPEC.md").read_text()


class TestConfigErrorsArePlain:
    def test_invalid_effort_message_has_no_pydantic_noise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _project(
            tmp_path,
            monkeypatch,
            FAKE_CONFIG.replace(
                '[agents.beta]\nadapter = "fake"',
                '[agents.beta]\nadapter = "fake"\neffort = "ultra"',
            ),
        )
        assert 'effort = "ultra"' in (root / ".orkestra" / "config.toml").read_text()
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 1
        flat = " ".join(result.output.split())
        assert "invalid configuration" in flat
        assert "agents.beta.effort" in flat
        assert "pydantic" not in flat.lower()

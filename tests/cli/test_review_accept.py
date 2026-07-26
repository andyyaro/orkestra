"""The review → accept journey: summaries, confirmation, and hard rules."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.test_cli import FAKE_CONFIG, git_commit_all

runner = CliRunner()


@pytest.fixture
def finished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["run", "--offline"]).exit_code == 0
    return root


@pytest.fixture
def blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "blocked"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(root), "--non-interactive"]).exit_code == 0
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG)
    (root / "SPEC.md").write_text("# Doomed\nFAKE:fail:always\n")
    git_commit_all(root)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["run", "--offline"])
    assert result.exit_code == 2  # waiting on a human decision
    return root


class TestReview:
    def test_summary_contents(self, finished: Path) -> None:
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 0, result.output
        out = result.output
        assert "status:" in out and "complete" in out
        assert "tasks finished" in out
        assert "starting point: your code as of commit" in out
        assert "verification:" in out  # honest wording tested in test_fleet_fixes
        assert "independent review" in out
        assert "commit(s)" in out
        assert "orkestra accept" in out
        # no internal branch name in the friendly summary
        assert "ork/run_" not in out

    def test_full_patch(self, finished: Path) -> None:
        result = runner.invoke(app, ["review", "--full"])
        assert result.exit_code == 0
        assert "diff --git" in result.output

    def test_partial_run_warns(self, blocked: Path) -> None:
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 0, result.output
        assert "not complete" in result.output
        assert "--allow-partial" in result.output


class TestAcceptConfirmation:
    def test_default_is_no(self, finished: Path) -> None:
        # Plain Enter at the prompt must decline.
        result = runner.invoke(app, ["accept"], input="\n")
        assert result.exit_code == 0, result.output
        assert "nothing changed" in result.output
        assert not list(finished.glob("fake-task_*.txt"))

    def test_explicit_yes_at_prompt(self, finished: Path) -> None:
        result = runner.invoke(app, ["accept"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output
        assert list(finished.glob("fake-task_*.txt"))

    def test_yes_flag_for_automation(self, finished: Path) -> None:
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output

    def test_accept_records_durable_event_with_merge_sha(self, finished: Path) -> None:
        """Accept is the only moment work becomes true of the user's branch;
        it must leave a durable event naming the merge commit."""
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 0, result.output
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=finished, capture_output=True, text=True
        ).stdout.strip()
        from orkestra.app import build_app

        application = build_app(finished, offline=True)
        try:
            run = application.store.latest_run()
            assert run is not None
            events = application.store.events_for_run(run.run_id, limit=1000)
            payloads = [json.loads(e["data"]) for e in events if e["data"]]
            accepted = [p for p in payloads if isinstance(p, dict) and p.get("run_accepted")]
            assert len(accepted) == 1
            assert accepted[0]["merge_sha"] == head
            assert accepted[0]["integration_branch"] == run.integration_branch
            assert accepted[0]["target_branch"]
        finally:
            application.close()

    def test_preflight_shows_summary(self, finished: Path) -> None:
        result = runner.invoke(app, ["accept"], input="\n")
        out = result.output
        assert "About to accept run" in out
        assert "run state: complete" in out
        assert "no uncommitted changes to tracked files" in " ".join(out.split())


class TestCompleteRunEnforcement:
    def test_incomplete_run_refused(self, blocked: Path) -> None:
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 1
        assert "not complete" in result.output
        assert "--allow-partial" in result.output
        assert "orkestra resume" in result.output
        # merge alias enforces identically (no warn-and-continue anymore)
        result = runner.invoke(app, ["merge", "--yes"])
        assert result.exit_code == 1
        assert "not complete" in result.output

    def test_allow_partial_requires_confirmation(self, blocked: Path) -> None:
        result = runner.invoke(app, ["accept", "--allow-partial"], input="\n")
        assert result.exit_code == 0, result.output
        assert "ACCEPTING A PARTIAL RESULT" in result.output
        assert "nothing changed" in result.output  # default declined

    def test_allow_partial_with_yes(self, blocked: Path) -> None:
        result = runner.invoke(app, ["accept", "--allow-partial", "--yes"])
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output


class TestAcceptSafety:
    def test_refuses_from_internal_branch(self, finished: Path) -> None:
        integration = subprocess.run(
            ["git", "branch", "--list", "ork/*/integration"],
            cwd=finished,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[-1]
        subprocess.run(["git", "checkout", "-q", integration], cwd=finished, check=True)
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 1
        assert "internal" in result.output.replace("\n", " ")
        assert "git checkout main" in result.output

    def test_untracked_collision_refused(self, finished: Path) -> None:
        # An untracked user file colliding with a file the run created:
        # find one of the run's files from the review output.
        review = runner.invoke(app, ["review"]).output
        import re

        match = re.search(r"fake-task_[a-f0-9]+\.txt", review)
        assert match, review
        (finished / match.group(0)).write_text("my unrelated note\n")
        result = runner.invoke(app, ["accept", "--yes"])
        assert result.exit_code == 1
        assert "would be overwritten" in result.output

    def test_cleanup_only_after_success(self, finished: Path) -> None:
        # A declined confirmation must not clean up anything.
        result = runner.invoke(app, ["accept", "--cleanup"], input="\n")
        assert "tidied up" not in result.output
        branches = subprocess.run(
            ["git", "branch", "--list", "ork/*"],
            cwd=finished,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert branches != ""  # everything still there
        # Successful acceptance cleans up.
        result = runner.invoke(app, ["accept", "--cleanup", "--yes"])
        assert result.exit_code == 0
        assert "tidied up" in result.output

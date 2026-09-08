"""`orkestra doctor` answers the three questions about the gate itself.

Can each command start, does it pass in a fresh checkout of HEAD, and does
it actually read the tree it is pointed at. All three before any quota is
spent, in the command QUICKSTART tells every user to run.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orkestra.cli.main import app
from tests.cli.asserts import assert_exit
from tests.cli.test_cli import FAKE_CONFIG, git_commit_all

runner = CliRunner()

PYTEST_GATE = f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider tests"


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verify: str) -> Path:
    root = tmp_path / "proj"
    monkeypatch.chdir(tmp_path)
    assert_exit(runner.invoke(app, ["init", str(root), "--non-interactive"]), 0)
    (root / ".orkestra" / "config.toml").write_text(FAKE_CONFIG + verify)
    (root / "SPEC.md").write_text("# Demo\nBuild a widget.\n")
    (root / "widget.py").write_text("VALUE = 41\n\n\ndef bump() -> int:\n    return VALUE + 1\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_widget.py").write_text(
        "from widget import bump\n\n\ndef test_bump() -> None:\n    assert bump() == 42\n"
    )
    git_commit_all(root)
    monkeypatch.chdir(root)
    return root


class TestDoctorVerifyRows:
    def test_unbound_gate_is_a_problem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(
            tmp_path,
            monkeypatch,
            '\n[verify]\ncommands = ["true"]\nbinding_check = true\n',
        )
        result = runner.invoke(app, ["doctor"])
        print(result.output)
        assert_exit(result, 1)
        assert "NOT bound" in result.output

    def test_bound_gate_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _project(tmp_path, monkeypatch, f'\n[verify]\ncommands = ["{PYTEST_GATE}"]\n')
        result = runner.invoke(app, ["doctor"])
        print(result.output)
        assert_exit(result, 0)
        assert "bound" in result.output

    def test_unresolvable_command_is_caught_before_anything_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(tmp_path, monkeypatch, '\n[verify]\ncommands = ["definitely-not-a-binary-xyz"]\n')
        result = runner.invoke(app, ["doctor"])
        print(result.output)
        assert_exit(result, 1)
        assert "cannot start" in result.output

    def test_gate_that_fails_in_a_fresh_checkout_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(
            tmp_path,
            monkeypatch,
            '\n[verify]\ncommands = ["false"]\nbinding_check = true\n',
        )
        result = runner.invoke(app, ["doctor"])
        print(result.output)
        assert_exit(result, 1)
        assert "fails" in result.output

    def test_no_gate_is_named_but_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _project(tmp_path, monkeypatch, "")
        result = runner.invoke(app, ["doctor"])
        print(result.output)
        assert_exit(result, 0)
        assert "no gate is configured" in result.output

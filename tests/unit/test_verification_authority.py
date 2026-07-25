"""v0.5.0: the user's [verify] commands are the authoritative gate."""

from __future__ import annotations

import pytest

from orkestra.verify.runner import CommandResult, VerificationOutcome, gate_command_problem


class TestGateValidation:
    @pytest.mark.parametrize(
        "command",
        [
            "python3 -m unittest discover -q",
            "true",
            "git status",
        ],
    )
    def test_runnable_commands_accepted(self, command: str) -> None:
        assert gate_command_problem(command) is None

    @pytest.mark.parametrize(
        ("command", "fragment"),
        [
            ("run the tests (they should pass)", "shell/prose syntax"),
            ("pytest | tee out.txt", "shell/prose syntax"),
            ("python3 -c 'import x; assert x'", "shell/prose syntax"),
            ("make test && echo ok", "shell/prose syntax"),
            ("definitely-not-a-real-binary-xyz --check", "not an executable"),
            ("", "empty"),
            ("   ", "empty"),
            ('unbalanced "quote', "cannot be parsed"),
        ],
    )
    def test_unrunnable_commands_rejected(self, command: str, fragment: str) -> None:
        problem = gate_command_problem(command)
        assert problem is not None
        assert fragment in problem

    def test_lenient_mode_allows_user_shell_syntax_but_checks_executable(self) -> None:
        # user-authored commands aren't second-guessed on syntax…
        assert gate_command_problem("python3 -c 'import x'", strict=False) is None
        # …but a missing executable is still caught before any agent runs
        problem = gate_command_problem("nope-not-here --x", strict=False)
        assert problem is not None and "not an executable" in problem


class TestFailureDetail:
    def test_failure_detail_includes_output(self) -> None:
        outcome = VerificationOutcome(
            results=[
                CommandResult("true", 0, 0.1, "fine", ""),
                CommandResult("pytest", 1, 0.2, "3 failed", "AssertionError: boom"),
            ]
        )
        detail = outcome.failure_detail()
        assert "pytest" in detail
        assert "3 failed" in detail
        assert "AssertionError: boom" in detail
        assert "fine" not in detail  # passing command's output is noise here

    def test_failure_detail_truncates(self) -> None:
        outcome = VerificationOutcome(results=[CommandResult("x", 1, 0.1, "y" * 10_000, "")])
        detail = outcome.failure_detail(500)
        assert len(detail) < 600
        assert "truncated" in detail

    def test_no_output_is_stated(self) -> None:
        outcome = VerificationOutcome(results=[CommandResult("x", 2, 0.1, "", "")])
        assert "(no output)" in outcome.failure_detail()

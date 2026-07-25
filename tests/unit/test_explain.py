"""Unit tests: plain-language explanations."""

from __future__ import annotations

from orkestra.kernel.explain import explain_block
from orkestra.schemas.agent import AgentResult, ErrorKind, ResultStatus
from orkestra.schemas.common import AttemptState
from orkestra.store.repo import AttemptRow


def attempt(kind: ErrorKind) -> AttemptRow:
    return AttemptRow(
        attempt_id="a",
        task_id="t",
        run_id="r",
        agent="x",
        role="primary",
        state=AttemptState.FAILED,
        workspace="",
        result=AgentResult(status=ResultStatus.ERROR, error_kind=kind),
    )


class TestExplainBlock:
    def test_review_exhausted(self) -> None:
        text = explain_block("review cycles exhausted")
        assert "max_review_cycles" in text and "retry" in text

    def test_no_reviewer(self) -> None:
        text = explain_block("no independent reviewer could produce a verdict")
        assert "doctor" in text

    def test_bad_acceptance_command(self) -> None:
        text = explain_block("verification setup error: command not found: 'greet.py'")
        assert "[verify]" in text

    def test_auth_dominant(self) -> None:
        text = explain_block(
            "Task 'x' failed with all available agents (attempt budget exhausted)",
            [attempt(ErrorKind.AUTH), attempt(ErrorKind.AUTH), attempt(ErrorKind.CRASH)],
        )
        assert "signed out" in text

    def test_rate_limit_dominant(self) -> None:
        text = explain_block("attempt budget exhausted", [attempt(ErrorKind.RATE_LIMIT)])
        assert "rate limits" in text or "window" in text

    def test_generic_exhaustion_mentions_fresh_checkout(self) -> None:
        text = explain_block("attempt budget exhausted", [])
        assert "fresh checkout" in text

    def test_policy(self) -> None:
        assert "protect" in explain_block("policy violation: diff touches protected path")

    def test_token_budget(self) -> None:
        assert "token_budget" in explain_block(
            "all candidate agents failed or exceeded token budgets"
        )

    def test_unknown_reason_fallback(self) -> None:
        assert "retry" in explain_block("mystery condition xyz")

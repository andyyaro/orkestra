"""Unit tests: policy engine — review separation, budgets, diff path checks."""

from __future__ import annotations

from orkestra.policy import PolicyEngine
from orkestra.schemas.config import PolicyConfig
from orkestra.schemas.task import Assignment


def engine(**overrides: object) -> PolicyEngine:
    return PolicyEngine(
        PolicyConfig.model_validate(overrides),
        enabled_agents=["claude", "codex", "anti"],
    )


class TestAssignment:
    def test_ok(self) -> None:
        decision = engine().check_assignment(
            Assignment(primary="claude", reviewers=["codex"], fallbacks=["anti"])
        )
        assert decision.allowed

    def test_self_review_rejected(self) -> None:
        decision = engine().check_assignment(Assignment(primary="claude", reviewers=["claude"]))
        assert not decision.allowed
        assert any("independent" in v for v in decision.violations)

    def test_unknown_agent_rejected(self) -> None:
        decision = engine().check_assignment(Assignment(primary="ghost", reviewers=["codex"]))
        assert not decision.allowed

    def test_review_required_by_default(self) -> None:
        decision = engine().check_assignment(Assignment(primary="claude"))
        assert not decision.allowed

    def test_review_optional_when_configured(self) -> None:
        decision = engine(require_review=False).check_assignment(Assignment(primary="claude"))
        assert decision.allowed

    def test_reviewer_pairing(self) -> None:
        assert not engine().check_reviewer("codex", "codex").allowed
        assert engine().check_reviewer("codex", "claude").allowed


class TestBudgets:
    def test_attempt_budget(self) -> None:
        e = engine(max_attempts_per_task=2)
        assert e.check_attempt_budget(1).allowed
        assert not e.check_attempt_budget(2).allowed

    def test_review_budget(self) -> None:
        e = engine(max_review_cycles=1)
        assert e.check_review_budget(1).allowed
        assert not e.check_review_budget(2).allowed


class TestDiffPaths:
    def test_normal_paths_ok(self) -> None:
        assert engine().check_diff_paths(["src/app.py", "tests/test_app.py"]).allowed

    def test_git_internals_rejected(self) -> None:
        decision = engine().check_diff_paths([".git/hooks/pre-commit"])
        assert not decision.allowed

    def test_traversal_rejected(self) -> None:
        assert not engine().check_diff_paths(["../outside.txt"]).allowed
        assert not engine().check_diff_paths(["/etc/passwd"]).allowed

    def test_protected_paths_rejected(self) -> None:
        decision = engine().check_diff_paths([".github/workflows/ci.yml"])
        assert not decision.allowed

    def test_protected_prefix_is_component_wise(self) -> None:
        # ".github-tools" must NOT match protected ".github/workflows"
        assert engine().check_diff_paths([".github-tools/x.yml"]).allowed

    def test_unicode_and_spaces_ok(self) -> None:
        assert engine().check_diff_paths(["docs/über file.md"]).allowed


class TestPush:
    def test_denied_by_default(self) -> None:
        assert not engine().check_push().allowed

    def test_opt_in(self) -> None:
        assert engine(allow_push=True).check_push().allowed

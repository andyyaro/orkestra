"""Unit tests: quota tracker — budgets, cooldowns, selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.kernel.quota import QuotaTracker
from orkestra.schemas.agent import Usage
from orkestra.schemas.config import ProjectConfig
from orkestra.store import Database, Store


def make_config(alpha_budget: int | None = None) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "version": 1,
            "project": {"name": "q"},
            "agents": {
                "alpha": {
                    "adapter": "fake",
                    **({"token_budget": alpha_budget} if alpha_budget else {}),
                },
                "beta": {"adapter": "fake"},
            },
            "director": {"agent": "alpha"},
        }
    )


@pytest.fixture
def tracker(tmp_path: Path) -> QuotaTracker:
    store = Store(Database(tmp_path / "q.db"))
    run_id = store.create_run("q")
    return QuotaTracker(
        config=make_config(alpha_budget=1000),
        store=store,
        run_id=run_id,
        cooldown_base_s=10.0,
    )


class TestBudgets:
    def test_unlimited_by_default(self, tracker: QuotaTracker) -> None:
        tracker.store.add_usage(tracker.run_id, "beta", None, Usage(input_tokens=10_000_000))
        assert not tracker.budget_exhausted("beta")

    def test_exhaustion_counts_input_plus_output(self, tracker: QuotaTracker) -> None:
        tracker.store.add_usage(
            tracker.run_id, "alpha", None, Usage(input_tokens=600, output_tokens=300)
        )
        assert not tracker.budget_exhausted("alpha")
        tracker.store.add_usage(
            tracker.run_id, "alpha", None, Usage(input_tokens=50, output_tokens=50)
        )
        assert tracker.budget_exhausted("alpha")

    def test_budget_is_per_run(self, tmp_path: Path) -> None:
        store = Store(Database(tmp_path / "q2.db"))
        run1, run2 = store.create_run("a"), store.create_run("b")
        store.add_usage(run1, "alpha", None, Usage(input_tokens=5000))
        tracker = QuotaTracker(config=make_config(1000), store=store, run_id=run2)
        assert not tracker.budget_exhausted("alpha")


class TestCooldowns:
    def test_escalation_and_reset(self, tracker: QuotaTracker) -> None:
        assert tracker.note_rate_limit("alpha") == 10.0
        assert tracker.note_rate_limit("alpha") == 20.0
        assert tracker.note_rate_limit("alpha") == 40.0
        assert tracker.cooling_down("alpha")
        tracker.note_success("alpha")
        assert not tracker.cooling_down("alpha")
        assert tracker.note_rate_limit("alpha") == 10.0  # strikes reset

    def test_cap(self, tracker: QuotaTracker) -> None:
        tracker.cooldown_max_s = 25.0
        tracker.note_rate_limit("alpha")
        tracker.note_rate_limit("alpha")
        assert tracker.note_rate_limit("alpha") == 25.0


class TestPick:
    def test_prefers_primary_when_eligible(self, tracker: QuotaTracker) -> None:
        assert tracker.pick([], "alpha", ["beta"]) == ("alpha", 0.0)

    def test_skips_cooling_agent_immediately(self, tracker: QuotaTracker) -> None:
        tracker.note_rate_limit("alpha")
        agent, wait = tracker.pick([], "alpha", ["beta"])
        assert agent == "beta"
        assert wait == 0.0

    def test_waits_for_soonest_when_all_cooling(self, tracker: QuotaTracker) -> None:
        tracker.note_rate_limit("alpha")  # 10s
        tracker.note_rate_limit("beta")  # 10s
        tracker.note_rate_limit("alpha")  # 20s -> beta is soonest
        agent, wait = tracker.pick([], "alpha", ["beta"])
        assert agent == "beta"
        assert 0.0 < wait <= 10.0

    def test_budget_exhausted_excluded(self, tracker: QuotaTracker) -> None:
        tracker.store.add_usage(tracker.run_id, "alpha", None, Usage(input_tokens=2000))
        assert tracker.pick([], "alpha", ["beta"]) == ("beta", 0.0)
        assert tracker.pick(["beta"], "alpha", ["beta"]) == (None, 0.0)

    def test_failed_agents_excluded(self, tracker: QuotaTracker) -> None:
        assert tracker.pick(["alpha", "beta"], "alpha", ["beta"]) == (None, 0.0)

"""Unit tests: capability matrix, ranking, ledger feedback, probe evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.capabilities.ledger import record_task_outcome
from orkestra.capabilities.matrix import build_matrix, rank_agents
from orkestra.capabilities.probes import STANDARD_PROBES, _evaluate
from orkestra.schemas.capability import CapabilityObservation
from orkestra.store import Database, Store


def obs(agent: str, capability: str, passed: bool, source: str = "probe:x") -> CapabilityObservation:
    return CapabilityObservation(
        agent=agent, capability=capability, source=source, objective_pass=passed
    )


class TestMatrix:
    def test_scores_require_evidence(self) -> None:
        matrix = build_matrix([])
        assert matrix.scores == {}
        assert matrix.score_for("anyone", "anything") is None

    def test_scores_from_observations(self) -> None:
        matrix = build_matrix([
            obs("a", "implementation", True),
            obs("a", "implementation", True),
            obs("a", "implementation", False),
        ])
        score = matrix.score_for("a", "implementation")
        assert score is not None
        assert 0.4 < score.score < 0.8
        assert score.confidence == pytest.approx(3 / 5)
        assert len(score.evidence) == 3  # every score carries its evidence

    def test_recency_weighting(self) -> None:
        improving = build_matrix([
            obs("a", "x", False), obs("a", "x", False), obs("a", "x", True),
        ])
        declining = build_matrix([
            obs("a", "x", True), obs("a", "x", False), obs("a", "x", False),
        ])
        assert improving.score_for("a", "x").score > declining.score_for("a", "x").score

    def test_judged_scores_used_when_no_objective(self) -> None:
        observation = CapabilityObservation(
            agent="a", capability="style", source="probe:j", judged_score=0.8
        )
        matrix = build_matrix([observation])
        assert matrix.score_for("a", "style").score == pytest.approx(0.8)


class TestRanking:
    def test_evidence_beats_unknown(self) -> None:
        matrix = build_matrix([
            obs("strong", "implementation", True),
            obs("strong", "implementation", True),
            obs("strong", "implementation", True),
            obs("weak", "implementation", False),
            obs("weak", "implementation", False),
        ])
        ranked = rank_agents(matrix, "implementation", ["weak", "unknown", "strong"])
        assert ranked[0] == "strong"
        assert ranked[-1] == "weak"

    def test_stable_order_without_evidence(self) -> None:
        matrix = build_matrix([])
        assert rank_agents(matrix, "x", ["one", "two", "three"]) == ["one", "two", "three"]


class TestLedgerFeedback:
    def test_task_outcomes_become_observations(self, tmp_path: Path) -> None:
        store = Store(Database(tmp_path / "db.sqlite"))
        run_id = store.create_run("demo")
        record_task_outcome(store, run_id, "codex", "1.0", "task_1", "implement",
                            succeeded=True)
        record_task_outcome(store, run_id, "codex", "1.0", "task_2", "review",
                            succeeded=False)
        implementation = store.observations_for("codex", "implementation")
        bug_detection = store.observations_for("codex", "bug_detection")
        assert len(implementation) == 1 and implementation[0].objective_pass
        assert len(bug_detection) == 1 and not bug_detection[0].objective_pass
        matrix = build_matrix(store.observations_for("codex"))
        assert matrix.score_for("codex", "implementation").score == 1.0


class TestProbeEvaluation:
    def test_json_discipline_probe(self) -> None:
        probe = next(p for p in STANDARD_PROBES if p.probe_id == "json-discipline-1")
        assert _evaluate(probe, '{"status": "ready", "count": 3}')
        assert _evaluate(probe, 'Sure! ```json\n{"status": "ready", "count": 3}\n```')
        assert not _evaluate(probe, '{"status": "ready", "count": 4}')
        assert not _evaluate(probe, "not json")

    def test_code_reasoning_probe(self) -> None:
        probe = next(p for p in STANDARD_PROBES if p.probe_id == "code-reasoning-1")
        assert _evaluate(probe, '{"answer": 9}')
        assert not _evaluate(probe, '{"answer": 7}')

    def test_instruction_probe(self) -> None:
        probe = next(p for p in STANDARD_PROBES if p.probe_id == "instruction-following-1")
        assert _evaluate(probe, "ORKESTRA-READY")
        assert not _evaluate(probe, "Sure, here is a long paragraph explaining that "
                                    "I would reply ORKESTRA-READY")

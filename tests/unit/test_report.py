"""Unit tests: report generation and redaction of exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.report.final import build_report, render_json, render_markdown
from orkestra.schemas.agent import AgentResult, ResultStatus, Usage
from orkestra.schemas.common import AttemptState, RunState, TaskKind, TaskState
from orkestra.schemas.decision import DecisionOption, HumanDecision
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.store import Database, Store


@pytest.fixture
def populated(tmp_path: Path) -> tuple[Store, str]:
    store = Store(Database(tmp_path / "r.db"))
    run_id = store.create_run(
        "report-demo",
        payload={
            "agents": {
                "alpha": {
                    "adapter": "fake",
                    "version": "1.0",
                    "available": "True",
                    "auth_ready": "True",
                }
            },
            "analysis": {"summary": "a demo project", "risks": ["low coverage"]},
        },
    )
    store.set_run_git(run_id, "abc123def456", "ork/run/integration")
    task_id = store.add_task(
        run_id,
        TaskSpec(key="build", title="Build it", kind=TaskKind.IMPLEMENT),
        Assignment(primary="alpha", reviewers=["beta"]),
    )
    attempt = store.create_attempt(task_id, run_id, "alpha", "primary")
    store.finish_attempt(
        attempt,
        AttemptState.SUCCEEDED,
        AgentResult(status=ResultStatus.OK, final_text="done with sk-ant-api03-topsecret1234"),
    )
    store.set_task_state(task_id, TaskState.READY)
    store.add_usage(
        run_id, "alpha", attempt, Usage(input_tokens=100, output_tokens=50, total_cost_usd=0.02)
    )
    store.add_ledger_entry(run_id, "alpha", task_id, "implement", "succeeded")
    store.add_decision(
        HumanDecision(
            decision_id="dec_r1",
            run_id=run_id,
            question="Ship it? token=sk-abcdefghijklmnop123",
            why_blocked="example",
            options=[DecisionOption(key="yes", label="Yes")],
        )
    )
    store.set_run_state(run_id, RunState.ANALYZING)
    return store, run_id


class TestReport:
    def test_build_report_structure(self, populated: tuple[Store, str]) -> None:
        store, run_id = populated
        report = build_report(store, run_id)
        assert report["run"]["project"] == "report-demo"
        assert report["tasks"][0]["key"] == "build"
        assert report["tasks"][0]["attempts"][0]["agent"] == "alpha"
        assert report["usage"][0]["input_tokens"] == 100
        assert report["decisions"][0]["decision_id"] == "dec_r1"

    def test_markdown_renders_and_redacts(self, populated: tuple[Store, str]) -> None:
        store, run_id = populated
        markdown = render_markdown(build_report(store, run_id))
        assert "# Orkestra Run Report — report-demo" in markdown
        assert "| build | implement |" in markdown
        assert "sk-abcdefghijklmnop123" not in markdown  # redacted
        assert "[REDACTED]" in markdown

    def test_json_renders_and_redacts(self, populated: tuple[Store, str]) -> None:
        store, run_id = populated
        rendered = render_json(build_report(store, run_id))
        assert "report-demo" in rendered
        assert "sk-abcdefghijklmnop123" not in rendered

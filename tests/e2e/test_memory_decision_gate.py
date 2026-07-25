"""Resolved human decisions, through the process that actually resolves them.

`apply_decision` runs inside `orkestra approve`, a *different process* from the
one that ran `execute()`. Memory was only ever opened inside `execute()`, so
`self._memory` is None there and always would be: recording a decision was not
merely unwired, it was unreachable. With no DECISION memory ever written, the
pre-action gate's rejected-alternative tier filtered for decisions, found none
every time, and nothing stopped an agent re-proposing what a human had just
turned down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from orkestra.memory import open_memory
from orkestra.schemas.decision import DecisionOption, HumanDecision
from tests.conftest import REQUIRE_MEMORY_EXTRA_ENV, missing_memory_extra_is_fatal
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec

if TYPE_CHECKING:
    from pathlib import Path

try:
    import provalume  # noqa: F401
except ImportError as exc:  # pragma: no cover - depends on the installed extras
    if missing_memory_extra_is_fatal():
        pytest.fail(
            f"{REQUIRE_MEMORY_EXTRA_ENV} is set, but the Provalume extra is not "
            f"installed, so the decision gate would go unverified: {exc}.",
            pytrace=False,
        )
    pytest.skip("the Provalume extra is not installed", allow_module_level=True)

pytestmark = pytest.mark.e2e


async def test_a_resolved_decision_reaches_the_gate_in_a_later_run(tmp_path: Path) -> None:
    """The whole point of recording ``rejected``: the next run is warned.

    Driven through `apply_decision` with no live run — the state `orkestra
    approve` is always in — and read back through a fresh client on the same
    database, which is what the next run does.
    """
    app = await make_project(tmp_path)
    try:
        run_id = await manual_run(
            app, [(spec("implement", "Add a thing"), assign("alpha", "beta"))]
        )
        task_id = app.store.tasks_for_run(run_id)[0].task_id
        decision = HumanDecision(
            decision_id="dec-parallelism",
            run_id=run_id,
            task_id=task_id,
            question="How should the integration suite run?",
            why_blocked="the suite deadlocks under parallel execution",
            options=[
                DecisionOption(key="serial", label="run serially"),
                DecisionOption(key="xdist", label="pytest-xdist -n auto"),
            ],
            recommendation="serial",
        )
        app.store.add_decision(decision)

        # No `execute()` in this process, exactly as in `orkestra approve`.
        assert app.orchestrator._memory is None
        app.orchestrator.apply_decision(
            "dec-parallelism", "serial", note="the db fixture is not parallel-safe"
        )

        memory = open_memory(app.root, app.config, run_id="run-2")
        assert memory is not None, "the memory database did not open for the next run"
        try:
            warning = memory.preflight_warning(commands=["pytest-xdist -n auto tests"])
            context = memory.brief_context(title="integration suite parallelism", task_id="t9")
        finally:
            memory.close()
    finally:
        app.close()

    assert "already rejected" in warning, (
        f"a human's rejected alternative never reached the gate: {warning!r}"
    )
    assert "pytest-xdist" in warning
    assert "run serially" in context, (
        f"the decision itself never became recallable context: {context!r}"
    )

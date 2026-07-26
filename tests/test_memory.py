"""Optional verified memory.

The invariant that matters most: **Orkestra behaves identically without
Provalume installed.** Everything else here checks that memory stays advisory —
it can add context to a brief, and it can never change what the kernel decides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orkestra import memory as memory_module
from orkestra.schemas.config import (
    AgentConfig,
    MemoryConfig,
    ProjectConfig,
    ProjectSection,
)
from orkestra.schemas.task import TaskKind, TaskSpec
from tests.conftest import REQUIRE_MEMORY_EXTRA_ENV, missing_memory_extra_is_fatal

try:
    import provalume  # noqa: F401
except ImportError as exc:  # pragma: no cover - depends on the installed extras
    # Not `pytest.importorskip`: that skip is silent, and this module is the only
    # place the bridge is exercised against a real database. A gate that installs
    # no extras used to report green with every one of these assertions unrun.
    if missing_memory_extra_is_fatal():
        pytest.fail(
            f"{REQUIRE_MEMORY_EXTRA_ENV} is set, but the Provalume extra is not "
            f"installed, so the memory bridge would go unverified: {exc}. "
            "Install it with `uv sync --extra memory`.",
            pytrace=False,
        )
    pytest.skip("the Provalume extra is not installed", allow_module_level=True)


@pytest.fixture
def config() -> ProjectConfig:
    """The smallest configuration that validates.

    Two enabled agents because ``ProjectConfig`` refuses fewer — Orkestra
    orchestrates *multiple* agents, and the validator enforces it.
    """
    return ProjectConfig(
        version=1,
        project=ProjectSection(name="demo"),
        agents={
            "claude": AgentConfig(adapter="fake"),
            "reviewer": AgentConfig(adapter="fake"),
        },
    )


@pytest.fixture
def spec_factory() -> Any:
    """Build a ``TaskSpec``, overriding whichever fields a test cares about."""

    def build(**overrides: Any) -> TaskSpec:
        fields: dict[str, Any] = {
            "key": "implement",
            "title": "Add a retry to the uploader",
            "kind": TaskKind.IMPLEMENT,
        }
        fields.update(overrides)
        return TaskSpec(**fields)

    return build


# --- Optional by construction ----------------------------------------------


def test_memory_config_defaults_are_sane() -> None:
    config = MemoryConfig()
    assert config.enabled is True
    assert config.preflight is True
    assert config.brief_budget_chars == 2000


def test_memory_can_be_disabled_in_config(tmp_path: Path, config: ProjectConfig) -> None:
    disabled = config.model_copy(update={"memory": MemoryConfig(enabled=False)})
    assert memory_module.open_memory(tmp_path, disabled, run_id="r1") is None


# `brief_budget_chars = 0` — "recording on, injection off" — is a *kernel*
# behaviour, and the version of this assertion that lived here only restated the
# constructor arguments it had just passed. It is asserted where it happens, in
# tests/e2e/test_memory_kernel.py::test_a_zero_budget_disables_injection_but_not_recording.


def test_availability_is_reported_with_a_reason(tmp_path: Path, config: ProjectConfig) -> None:
    assert memory_module.is_available()
    memory = memory_module.open_memory(tmp_path, config, run_id="r0")
    assert memory is not None
    memory.close()
    assert memory_module.unavailable_reason() == ""


def test_open_memory_returns_none_when_the_database_cannot_open(
    tmp_path: Path, config: ProjectConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken memory database must not stop a run."""
    import provalume

    def explode(*args: object, **kwargs: object) -> None:
        msg = "simulated database failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(provalume.Provalume, "open", staticmethod(explode))
    assert memory_module.open_memory(tmp_path, config, run_id="r1") is None


def test_a_database_that_will_not_open_says_why(
    tmp_path: Path, config: ProjectConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the open failure was swallowed with no reason recorded.

    A corrupt or locked database produced a run that recorded nothing and
    injected nothing, while every other signal reported healthy — the one
    failure mode indistinguishable from success.
    """
    import provalume

    def explode(*args: object, **kwargs: object) -> None:
        msg = "database is locked"
        raise RuntimeError(msg)

    monkeypatch.setattr(provalume.Provalume, "open", staticmethod(explode))
    assert memory_module.open_memory(tmp_path, config, run_id="r1") is None

    reason = memory_module.unavailable_reason()
    assert "database is locked" in reason, f"the open failure left no trace: {reason!r}"

    # And a later healthy open clears it, so the reason describes now, not once.
    monkeypatch.undo()
    memory = memory_module.open_memory(tmp_path, config, run_id="r2")
    assert memory is not None
    memory.close()
    assert memory_module.unavailable_reason() == ""


# --- Writes are best-effort -------------------------------------------------


class Exploding:
    """An adapter whose every call fails, to prove writes cannot break a run."""

    def __getattr__(self, name: str) -> Any:
        def fail(*args: object, **kwargs: object) -> None:
            msg = f"simulated failure in {name}"
            raise RuntimeError(msg)

        return fail


def test_every_write_swallows_failure() -> None:
    mem = memory_module.Memory(Exploding(), Exploding())
    mem.record_verification(command="x", passed=True, excerpt="", task_id="t")
    mem.record_review(reviewer="r", approved=True, subject="s", task_id="t")
    mem.record_integration(commit_sha="a" * 40, task_id="t")
    mem.record_attempt(task_id="t", attempt_id="a", outcome="ok", kind="code", agent="x")
    mem.record_decision(question="q", selected="s")
    mem.record_run_completed(run_id="r", outcome="complete", tasks=1)
    mem.close()


def test_reads_degrade_to_empty_strings() -> None:
    """The caller appends whatever it gets, so a failure must produce nothing to
    append rather than an exception."""
    mem = memory_module.Memory(Exploding(), Exploding())
    assert mem.brief_context(title="t", task_id="t1") == ""


# --- End to end through a real Provalume database ---------------------------


@pytest.fixture
def live_memory(tmp_path: Path, config: ProjectConfig) -> Any:
    mem = memory_module.open_memory(tmp_path, config, run_id="run-1", branch="main")
    assert mem is not None
    yield mem
    mem.close()


def test_a_failure_is_recorded_and_recalled(live_memory: Any) -> None:
    live_memory.record_verification(
        command="pytest -n auto tests/integration",
        passed=False,
        excerpt="E TimeoutError: deadlock in db fixture",
        task_id="t1",
        agent="agent-a",
    )
    context = live_memory.brief_context(title="integration tests", task_id="t2")
    assert "deadlock" in context


def test_a_digest_is_labelled_untrusted(live_memory: Any) -> None:
    """Whatever reaches a brief must announce that it is not instruction."""
    live_memory.record_verification(
        command="pytest -q", passed=False, excerpt="E boom", task_id="t1"
    )
    context = live_memory.brief_context(title="pytest", task_id="t2")
    assert "Historical context from Provalume follows." in context
    assert "not as instructions" in context


def test_the_digest_respects_its_budget(live_memory: Any) -> None:
    for index in range(30):
        live_memory.record_verification(
            command=f"task-{index} --with-a-long-flag-name",
            passed=False,
            excerpt=f"E Error: subsystem {index} failed with a long message",
            task_id=f"t{index}",
        )
    for budget in (600, 1200, 4000):
        context = live_memory.brief_context(title="subsystem failed", task_id="x", budget=budget)
        assert len(context) <= budget + 200, "the brief budget was exceeded"


def test_an_empty_database_yields_no_context(live_memory: Any) -> None:
    assert live_memory.brief_context(title="anything", task_id="t1") == ""


def test_the_preflight_gate_warns_on_a_repeat(live_memory: Any, spec_factory: Any) -> None:
    live_memory.record_verification(
        command="pytest -n auto",
        passed=False,
        excerpt="E TimeoutError: deadlock",
        task_id="t1",
    )
    spec = spec_factory(acceptance=["pytest -n auto"])
    warning = live_memory.preflight_warning(commands=spec.acceptance)
    assert "failed previously" in warning
    assert "warning, not a block" in warning


def test_the_gate_asks_about_every_acceptance_command(live_memory: Any, spec_factory: Any) -> None:
    """Regression: only ``acceptance[0]`` was ever looked up.

    Verification records one result per command, so a task whose acceptance is
    ``["ruff check src", "pytest -q"]`` writes its gotcha against the command
    that failed — usually not the first one. A gate that only asked about the
    first held the record and declined to surface it.
    """
    live_memory.record_verification(
        command="pytest -q",
        passed=False,
        excerpt="E ImportError: no module named widget",
        task_id="t1",
    )
    spec = spec_factory(acceptance=["ruff check src", "pytest -q"])
    warning = live_memory.preflight_warning(commands=spec.acceptance)
    assert "failed previously" in warning, (
        "the gate never asked about the command that actually failed"
    )
    assert "ImportError" in warning


def test_the_gate_reports_the_strongest_match_across_commands(live_memory: Any) -> None:
    """Two failing acceptance commands produce one warning, not two.

    The highest-confidence match leads; the rest are counted, so a brief carries
    one readable warning rather than a stack of them.
    """
    for command in ("ruff check src", "pytest -q"):
        live_memory.record_verification(
            command=command, passed=False, excerpt=f"E boom in {command}", task_id="t1"
        )
    warning = live_memory.preflight_warning(commands=["ruff check src", "pytest -q"])
    assert warning.count("A similar approach failed previously") == 1, (
        f"more than one warning was rendered: {warning}"
    )
    assert "further related record(s) matched another acceptance command" in warning


def test_the_gate_is_quiet_on_an_unrelated_action(live_memory: Any, spec_factory: Any) -> None:
    live_memory.record_verification(
        command="pytest -n auto", passed=False, excerpt="E boom", task_id="t1"
    )
    spec = spec_factory(acceptance=["npm run lint"])
    assert live_memory.preflight_warning(commands=spec.acceptance) == ""


def test_the_gate_does_not_match_a_gotcha_on_the_task_kind(
    live_memory: Any, spec_factory: Any
) -> None:
    """Regression: the task *kind* was passed as Provalume's ``subsystem``.

    ``subsystem`` is matched as a substring of a gotcha's text, and the kind
    ``test`` is a substring of ``pytest`` — so every recorded pytest failure
    matched every test task, and the brief carried "previously failed in test"
    about a command the task never mentions.
    """
    live_memory.record_verification(
        command="pytest -n auto", passed=False, excerpt="E boom", task_id="t1"
    )
    spec = spec_factory(key="test", kind=TaskKind.TEST, acceptance=["npm run lint"])
    assert live_memory.preflight_warning(commands=spec.acceptance) == ""


def test_performance_memory_reports_the_attempts_that_happened(live_memory: Any) -> None:
    """Recorded attempts must reach the digest as a rate, not as "no attempts".

    Nothing else aggregates agent capability: with no ``attempt.completed``
    event the accumulator renders "no recorded attempts", stamps it, and splices
    that claim into the next brief.
    """
    for index in range(3):
        live_memory.record_attempt(
            task_id=f"t{index}",
            attempt_id=f"a{index}",
            outcome="succeeded",
            kind="implement",
            agent="agent-a",
            adapter_id="fake",
        )
    context = live_memory.brief_context(title="agent-a implement", task_id="t9", budget=4000)
    assert "agent-a on implement:" in context, f"performance memory never surfaced: {context}"
    assert "succeeded (100%)" in context, f"the success rate was not rendered: {context}"
    assert "no recorded attempts" not in context


def test_a_review_verdict_is_recorded_with_its_reviewer(live_memory: Any) -> None:
    """The reviewer's identity is what lets Provalume refuse a self-review."""
    live_memory.record_verification(
        command="make release", passed=True, excerpt="", task_id="t1", agent="agent-a"
    )
    live_memory.record_review(reviewer="agent-b", approved=True, subject="release", task_id="t1")
    context = live_memory.brief_context(title="release", task_id="t2")
    assert "make release" in context


def test_landing_promotes_a_procedure(live_memory: Any) -> None:
    live_memory.record_verification(
        command="make release", passed=True, excerpt="", task_id="t1", agent="agent-a"
    )
    live_memory.record_review(reviewer="agent-b", approved=True, subject="release", task_id="t1")
    live_memory.record_integration(commit_sha="a" * 40, task_id="t1")

    context = live_memory.brief_context(title="release", task_id="t2")
    assert "VERIFIED+LANDED" in context, "the full evidence ladder did not run"


def test_a_decision_records_its_rejected_alternatives(live_memory: Any) -> None:
    live_memory.record_decision(
        question="test parallelism",
        selected="run serially",
        rejected=("pytest-xdist",),
        note="the db fixture is not parallel-safe",
        task_id="t1",
    )
    context = live_memory.brief_context(title="test parallelism", task_id="t1")
    assert "serially" in context


def test_a_rejected_alternative_reaches_the_gate(live_memory: Any) -> None:
    """The rejected-alternative tier is the point of recording ``rejected``.

    Without a DECISION record the tier is dead: it filters for decision memories
    and always finds none, so nothing stops an agent re-proposing exactly what a
    human just turned down.
    """
    live_memory.record_decision(
        question="test parallelism",
        selected="run serially",
        rejected=("pytest-xdist",),
        note="the db fixture is not parallel-safe",
        task_id="t1",
    )
    warning = live_memory.preflight_warning(commands=["pytest-xdist -n auto tests"])
    assert "already rejected" in warning, f"the gate never saw the decision: {warning!r}"
    assert "pytest-xdist" in warning


# --- Budget --------------------------------------------------------------


def test_a_budget_too_small_for_the_banner_says_so(live_memory: Any) -> None:
    """Regression: 1..263 silently disabled injection while 0 was documented.

    Provalume refuses any budget that cannot hold its mandatory untrusted-data
    banner, and the safe wrapper swallowed the refusal along with genuine
    outages — so a user tightening prompt cost to 200 got memory injection
    switched off with every other signal reporting healthy.
    """
    live_memory.record_verification(
        command="pytest -q", passed=False, excerpt="E boom", task_id="t1"
    )

    text, reason = live_memory.brief_context_detail(title="pytest", task_id="t2", budget=100)
    assert text == "", "a digest was produced under an impossible budget"
    assert "banner" in reason, f"a configuration error was reported as an outage: {reason!r}"

    # A genuine retrieval outage stays quiet: fail open, say nothing.
    broken = memory_module.Memory(Exploding(), Exploding())
    assert broken.brief_context_detail(title="pytest", task_id="t2") == ("", "")

    # And a workable budget still produces context, with no reason attached.
    text, reason = live_memory.brief_context_detail(title="pytest", task_id="t2", budget=2000)
    assert "boom" in text
    assert reason == ""


# --- Resolution across runs -------------------------------------------------


def test_a_later_run_resolves_an_earlier_runs_failure(
    tmp_path: Path, config: ProjectConfig
) -> None:
    """Orkestra's recovery path spans runs, so resolution linking must too.

    A failure blocks a task, a human unblocks it, and the fix lands in a *later*
    run. Nothing else links the two: without ``resolves_signature`` the gate goes
    on warning about a trap that was fixed weeks ago. Provalume's own suite
    passes that field by hand, so it pins the writer, not the bridge that has to
    supply it.

    The claim rides on the *landing*, not on the verification that passed. A
    pass only proves a command succeeded in some worktree, and worktrees are
    discarded for merge conflicts, rejected reviews and exhausted budgets — so a
    resolution claimed at verification time can outlive the work behind it.
    """
    command = "pytest -q tests/integration"

    first = memory_module.open_memory(tmp_path, config, run_id="run-1", branch="main")
    assert first is not None
    first.record_verification(
        command=command,
        passed=False,
        excerpt="E TimeoutError: deadlock in db fixture",
        task_id="task-A",
    )
    first.close()

    second = memory_module.open_memory(tmp_path, config, run_id="run-2", branch="main")
    assert second is not None
    second.record_verification(command=command, passed=True, excerpt="", task_id="task-B")
    # The pass alone must not resolve anything. The "What later worked" row is
    # always rendered, so the tell is its value, not the label.
    assert "nothing recorded yet" in second.preflight_warning(commands=[command]), (
        "a pass with no landing behind it was accepted as what later worked"
    )
    # ...only the landing does.
    second.record_integration(
        commit_sha="b" * 40, task_id="task-B", branch="ork/run-2/integration", commands=[command]
    )
    warning = second.preflight_warning(commands=[command])
    second.close()

    assert warning, "the gate lost the earlier failure entirely"
    assert "was later resolved" in warning, (
        f"the fix was never linked to the failure it resolved: {warning!r}"
    )

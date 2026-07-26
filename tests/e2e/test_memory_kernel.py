"""The memory hooks, driven through a real run.

`tests/test_memory.py` exercises the bridge in isolation. This file exercises
the *wiring*: that the kernel calls it at the right moments, in the right order,
and that a misbehaving memory cannot take a run down with it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from orkestra.kernel import scheduler as scheduler_module
from orkestra.schemas.agent import EventKind
from orkestra.schemas.common import RunState, TaskKind
from orkestra.schemas.config import MemoryConfig, VerifyConfig
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e

#: Distinctive on purpose. A spy that returns "" can only prove the kernel
#: *called* memory, never that what came back reached the brief — so the entire
#: read half of the integration could be deleted with every test still green.
CONTEXT_SENTINEL = "CONTEXT-SENTINEL-4f21"
WARNING_SENTINEL = "WARNING-SENTINEL-9ab3"


class SpyMemory:
    """Records the calls the kernel makes, and whether it was open at the time."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False
        self.calls_after_close: list[str] = []

    def _note(self, name: str) -> None:
        self.calls.append(name)
        if self.closed:
            self.calls_after_close.append(name)

    def brief_context_detail(self, **_: Any) -> tuple[str, str]:
        self._note("brief_context")
        return CONTEXT_SENTINEL, ""

    def preflight_warning(self, **_: Any) -> str:
        self._note("preflight_warning")
        return WARNING_SENTINEL

    def record_run_started(self, **_: Any) -> None:
        self._note("record_run_started")

    def record_attempt(self, **_: Any) -> None:
        self._note("record_attempt")

    def record_verification(self, **_: Any) -> None:
        self._note("record_verification")

    def record_review(self, **_: Any) -> None:
        self._note("record_review")

    def record_integration(self, **_: Any) -> None:
        self._note("record_integration")

    def record_decision(self, **_: Any) -> None:
        self._note("record_decision")

    def record_run_completed(self, **_: Any) -> None:
        self._note("record_run_completed")

    def close(self) -> None:
        self.closed = True


class ExplodingMemory(SpyMemory):
    """Every method raises. A run must not notice."""

    def _note(self, name: str) -> None:
        super()._note(name)
        msg = f"memory is broken: {name}"
        raise RuntimeError(msg)


def capture_briefs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The instructions actually handed to an adapter, in dispatch order.

    Asserting on `_render_brief` would test the renderer; this tests what the
    agent receives, which is the only thing that matters about a spliced digest.
    """
    seen: list[str] = []
    original = scheduler_module.Orchestrator._invoke

    async def spy(self: Any, adapter: Any, brief: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(brief.instructions)
        return await original(self, adapter, brief, *args, **kwargs)

    monkeypatch.setattr(scheduler_module.Orchestrator, "_invoke", spy)
    return seen


async def run_with(memory: SpyMemory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    try:
        # An acceptance command is required for the verification hook to fire at
        # all: `_verify` returns early when there is nothing to run.
        task = spec(
            "implement",
            "Add a thing",
            kind=TaskKind.IMPLEMENT,
            acceptance=["true"],
        )
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        return await app.orchestrator.execute(run_id)
    finally:
        app.close()


async def test_the_kernel_records_the_full_evidence_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = SpyMemory()
    state = await run_with(memory, tmp_path, monkeypatch)

    assert state is RunState.COMPLETE
    for expected in (
        "record_run_started",
        "brief_context",
        "preflight_warning",
        "record_attempt",
        "record_verification",
        "record_review",
        "record_integration",
        "record_run_completed",
    ):
        assert expected in memory.calls, f"{expected} was never recorded"
    assert memory.calls[0] == "record_run_started", (
        f"the journal opens with no `run.started`, so nothing downstream can "
        f"tell a finished run from one never seen: {memory.calls[:3]}"
    )


async def test_what_memory_returns_reaches_the_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: nothing asserted on the rendered brief.

    Both `_memory_sections` splices could be deleted — the digest and the
    pre-action warning computed and then thrown away — and the whole suite
    stayed green, because the spy returned "" and the tests only observed the
    call.
    """
    memory = SpyMemory()
    briefs = capture_briefs(monkeypatch)
    state = await run_with(memory, tmp_path, monkeypatch)

    assert state is RunState.COMPLETE
    assert briefs, "no brief ever reached an adapter — the test would be vacuous"
    brief = briefs[0]
    assert CONTEXT_SENTINEL in brief, "the retrieved digest never reached the brief"
    assert WARNING_SENTINEL in brief, "the pre-action warning never reached the brief"
    # Position is the control, not decoration: retrieved memory placed *before*
    # the instructions would be reading as instruction, which is what the
    # untrusted-data banner exists to deny.
    assert brief.index("Add a thing") < brief.index(CONTEXT_SENTINEL)
    assert brief.index("Add a thing") < brief.index(WARNING_SENTINEL)


class AskingMemory(SpyMemory):
    """Captures the command list the pre-action gate is asked about."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[list[str]] = []

    def preflight_warning(self, **kwargs: Any) -> str:
        self._note("preflight_warning")
        self.asked.append(list(kwargs["commands"]))
        return WARNING_SENTINEL


async def test_the_gate_is_asked_about_every_acceptance_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: only ``acceptance[0]`` was ever passed to the gate.

    Verification records one result per command, so the gotcha is keyed on the
    command that failed — rarely the first. Asking about only the first meant
    the gate held records it could never be asked about.
    """
    memory = AskingMemory()
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    try:
        task = spec(
            "implement",
            "Add a thing",
            kind=TaskKind.IMPLEMENT,
            acceptance=["true", "echo second"],
        )
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
    finally:
        app.close()

    assert memory.asked, "the pre-action gate was never consulted"
    assert memory.asked[0] == ["true", "echo second"], (
        f"the gate was not asked about the commands verification runs: {memory.asked}"
    )


async def test_a_task_without_acceptance_asks_about_the_fallback_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the gate was asked about ``""`` for these tasks.

    `_verify` falls back to `config.verify.commands`, and records failures
    against them. The gate was handed the empty string instead, which skips both
    command-keyed tiers — leaving it unable to match anything it had recorded.
    """
    memory = AskingMemory()
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    monkeypatch.setattr(
        app.orchestrator,
        "config",
        app.config.model_copy(update={"verify": VerifyConfig(commands=["true"])}),
    )
    try:
        task = spec("implement", "Add a thing", kind=TaskKind.IMPLEMENT)
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
    finally:
        app.close()

    assert memory.asked, "the pre-action gate was never consulted"
    assert memory.asked[0] == ["true"], (
        f"the gate was asked about something verification never runs: {memory.asked}"
    )


async def test_a_zero_budget_disables_injection_but_not_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`brief_budget_chars = 0` is documented as "recording on, injection off".

    The assertion used to be a restatement of the constructor arguments; the
    behaviour it names lives in the kernel and was never exercised.
    """
    memory = SpyMemory()
    briefs = capture_briefs(monkeypatch)
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    monkeypatch.setattr(
        app.orchestrator,
        "config",
        app.config.model_copy(update={"memory": MemoryConfig(brief_budget_chars=0)}),
    )
    try:
        task = spec("implement", "Add a thing", kind=TaskKind.IMPLEMENT, acceptance=["true"])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
    finally:
        app.close()

    assert briefs, "no brief ever reached an adapter — the test would be vacuous"
    assert CONTEXT_SENTINEL not in briefs[0], "a zero budget still injected a digest"
    assert "brief_context" not in memory.calls, "memory was queried under a zero budget"
    # The valuable half is untouched: recording, and the pre-action gate.
    assert "record_verification" in memory.calls
    assert WARNING_SENTINEL in briefs[0]


async def test_a_budget_too_small_to_inject_anything_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: 1..263 silently disabled injection while only 0 was documented.

    Provalume refuses a budget that cannot hold its mandatory untrusted-data
    banner. That refusal used to be swallowed alongside genuine outages, so a
    user tightening prompt cost got injection switched off with every signal
    still reporting healthy. It is a configuration error and is now said once.
    """

    class TooSmallMemory(SpyMemory):
        def brief_context_detail(self, **_: Any) -> tuple[str, str]:
            self._note("brief_context")
            return "", "character budget 100 cannot hold the mandatory banner (264 required)"

    memory = TooSmallMemory()
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    monkeypatch.setattr(
        app.orchestrator,
        "config",
        app.config.model_copy(update={"memory": MemoryConfig(brief_budget_chars=100)}),
    )
    try:
        # Two tasks, because the setting is global: reporting it per task would
        # bury the run's real events under an identical line.
        tasks = [
            (
                spec(key, "Add a thing", kind=TaskKind.IMPLEMENT, acceptance=["true"]),
                assign("alpha", "beta"),
            )
            for key in ("implement", "document")
        ]
        run_id = await manual_run(app, tasks)
        await app.orchestrator.execute(run_id)
        warnings = [
            event["text"]
            for event in app.store.events_for_run(run_id)
            if event["kind"] == EventKind.WARNING.value and "brief_budget_chars" in event["text"]
        ]
        assert memory.calls.count("brief_context") == 2, (
            f"both tasks must have consulted memory for this to mean anything: {memory.calls}"
        )
    finally:
        app.close()

    assert warnings, "an unusable brief budget was applied without a word"
    assert len(warnings) == 1, f"the same configuration was reported per task: {warnings}"
    assert "264" in warnings[0], f"the warning does not say what would work: {warnings[0]}"


async def test_memory_that_will_not_open_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run with memory silently off must not look like one with it on.

    `open_memory` returns None for a corrupt database, a locked file, or a
    renamed project exactly as it does for "not installed" — and the run then
    records nothing and injects nothing while `doctor` stays green.
    """
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: None)
    monkeypatch.setattr(scheduler_module, "memory_unavailable_reason", lambda: "database is locked")
    app = await make_project(tmp_path)
    try:
        task = spec("implement", "Add a thing", kind=TaskKind.IMPLEMENT, acceptance=["true"])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
        warnings = [
            event["text"]
            for event in app.store.events_for_run(run_id)
            if event["kind"] == EventKind.WARNING.value and "memory is enabled" in event["text"]
        ]
    finally:
        app.close()

    assert warnings, "memory was requested, never started, and said nothing"
    assert "database is locked" in warnings[0], (
        f"the warning does not say why memory is off: {warnings[0]}"
    )


async def test_a_cancelled_run_records_its_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the cancellation path closed memory without recording anything.

    A `run.started` with no ending reads in the journal as a run still in
    flight, forever.
    """

    class CancelOnStart(SpyMemory):
        def record_run_started(self, **kwargs: Any) -> None:
            super().record_run_started(**kwargs)
            current = asyncio.current_task()
            assert current is not None
            current.cancel()

    memory = CancelOnStart()
    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: memory)
    try:
        task = spec("implement", "Add a thing", kind=TaskKind.IMPLEMENT, acceptance=["true"])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        with pytest.raises(asyncio.CancelledError):
            await app.orchestrator.execute(run_id)
    finally:
        app.close()

    assert "record_run_completed" in memory.calls, (
        f"a cancelled run left no outcome in the journal: {memory.calls}"
    )
    assert memory.calls_after_close == [], (
        f"the outcome was written after close() and silently lost: {memory.calls_after_close}"
    )


async def test_run_completion_is_recorded_before_memory_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `close()` ran in a `finally` that fired first.

    Every write after it landed on a closed client and was swallowed by the
    best-effort guard, so run completion silently never got recorded.
    """
    memory = SpyMemory()
    await run_with(memory, tmp_path, monkeypatch)

    assert memory.closed, "memory was never closed"
    assert memory.calls_after_close == [], (
        f"these writes happened after close() and would be silently lost: "
        f"{memory.calls_after_close}"
    )
    assert memory.calls[-1] == "record_run_completed"


async def test_a_memory_that_raises_on_every_call_does_not_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The invariant the guard exists for."""
    memory = ExplodingMemory()
    state = await run_with(memory, tmp_path, monkeypatch)

    assert state is RunState.COMPLETE
    assert memory.calls, "the kernel never reached memory at all — test is vacuous"


async def test_only_commands_that_actually_ran_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: recording iterated the requested commands, not the results.

    Verification stops at the first failure, so a later command may never run,
    and each command has its own exit code. Attributing the whole-run verdict to
    every requested command recorded passing and unrun commands as failures —
    which manufactures gotchas, and then false pre-action warnings.
    """
    recorded: list[tuple[str, bool]] = []

    class RecordingMemory(SpyMemory):
        def record_verification(self, **kwargs: Any) -> None:
            self._note("record_verification")
            recorded.append((kwargs["command"], kwargs["passed"]))

    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: RecordingMemory())
    try:
        # `false` fails, so `echo` never runs at all.
        task = spec("implement", "Add a thing", acceptance=["false", "echo unreachable"])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        await app.orchestrator.execute(run_id)
    finally:
        app.close()

    assert recorded, "verification was never recorded"
    assert all(cmd == "false" for cmd, _ in recorded), (
        f"a command that never ran was recorded: {recorded}"
    )
    assert not any(passed for _, passed in recorded), (
        f"a failing command was recorded as passing: {recorded}"
    )


async def test_every_attempt_that_ends_reaches_performance_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `record_attempt` was defined and never called.

    Performance memory has no other input. With no attempt event, Provalume
    aggregated nothing and published "<agent>: no recorded attempts at
    implement." — spliced into the next brief, stamped VERIFIED, about an agent
    that had just succeeded.

    Both endings must be recorded, attributed to the agent that actually ran:
    `alpha` fails, `beta` takes over as the fallback.
    """
    recorded: list[dict[str, Any]] = []

    class AttemptMemory(SpyMemory):
        def record_attempt(self, **kwargs: Any) -> None:
            self._note("record_attempt")
            recorded.append(kwargs)

    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: AttemptMemory())
    try:
        task = spec(
            "feat",
            "FAKE:fail_if_agent:alpha\nFAKE:write:out.txt:done",
            kind=TaskKind.IMPLEMENT,
            acceptance=["true"],
        )
        run_id = await manual_run(app, [(task, assign("alpha", "beta", ["beta"]))])
        assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
    finally:
        app.close()

    by_agent = {call["agent"]: call for call in recorded}
    assert set(by_agent) == {"alpha", "beta"}, (
        f"an attempt ended without reaching performance memory: {recorded}"
    )

    failed = by_agent["alpha"]
    assert failed["outcome"] == "failed"
    assert failed["error_kind"], f"the failure carried no error kind: {failed}"
    assert failed["fallback"] is False

    succeeded = by_agent["beta"]
    assert succeeded["outcome"] == "succeeded"
    assert succeeded["kind"] == "implement"
    assert succeeded["adapter_id"] == "fake"
    assert succeeded["attempt_id"], "no attempt id, so nothing links to the work it describes"
    assert succeeded["fallback"] is True, (
        "the fallback was recorded as a first-choice success, which is the "
        "statistic `fallbacks` exists to correct"
    )


async def test_the_recorded_excerpt_carries_the_actual_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the excerpt was `outcome.summary`, which holds no error.

    Fingerprinting a summary yields one signature for every failure of a given
    command, however unrelated — so the gate warns about a failure that never
    happened. The excerpt must carry captured output.
    """
    excerpts: list[str] = []

    class ExcerptMemory(SpyMemory):
        def record_verification(self, **kwargs: Any) -> None:
            self._note("record_verification")
            excerpts.append(kwargs["excerpt"])

    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: ExcerptMemory())
    try:
        # The marker must exist only in the *output*, never in the command text:
        # `outcome.summary` quotes the command, so a marker visible in the
        # command would make this test pass against the very bug it guards.
        # It lives in a committed helper script — a shell one-liner would be
        # dropped by `_gate_commands`, which screens plan-derived acceptance
        # entries for shell syntax because gates run without a shell.
        from tests.e2e.test_orchestration import GitRepo

        marker = "MARKER9c1f"
        script = app.root / "emit_marker.py"
        script.write_text(
            'import sys\nsys.stderr.write("MARK" + "ER9c1f\\n")\nraise SystemExit(1)\n'
        )
        repo = GitRepo(app.root)
        await repo._git("add", "-A")
        await repo._git("commit", "-m", "marker script")
        command = "python3 emit_marker.py"
        assert marker not in command, "the marker leaked into the command — test would be vacuous"
        task = spec("implement", "Add a thing", acceptance=[command])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        await app.orchestrator.execute(run_id)
    finally:
        app.close()

    assert excerpts, "verification was never recorded"
    assert any(marker in e for e in excerpts), (
        f"the captured output never reached the excerpt: {excerpts}"
    )


async def test_verification_and_review_share_the_attempt_they_concern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the two halves of the evidence chain were in different scopes.

    Provalume associates a review verdict with the work it examined by attempt
    id. Verification was recorded with no attempt at all, and the verdict was
    filed against the *reviewer's* freshly created attempt rather than the
    attempt under review — two scopes, neither containing the other's records.
    Nothing was ever stamped, so no memory could climb past `verified` and the
    top two rungs of the trust ladder were unreachable through a real run.
    """
    seen: dict[str, list[str | None]] = {"verification": [], "review": []}

    class AttemptMemory(SpyMemory):
        def record_verification(self, **kwargs: Any) -> None:
            self._note("record_verification")
            seen["verification"].append(kwargs.get("attempt_id"))

        def record_review(self, **kwargs: Any) -> None:
            self._note("record_review")
            seen["review"].append(kwargs.get("attempt_id"))

    app = await make_project(tmp_path)
    monkeypatch.setattr(scheduler_module, "open_memory", lambda *a, **k: AttemptMemory())
    try:
        task = spec("implement", "Add a thing", acceptance=["true"])
        run_id = await manual_run(app, [(task, assign("alpha", "beta"))])
        await app.orchestrator.execute(run_id)
    finally:
        app.close()

    assert seen["verification"], "verification was never recorded"
    assert seen["review"], "no review verdict was recorded"
    assert all(a is not None for a in seen["verification"]), (
        "verification carried no attempt id, so a verdict can never associate with it"
    )
    assert set(seen["review"]) == set(seen["verification"]), (
        f"the verdict was filed against a different attempt than the work it "
        f"reviewed: review={seen['review']} verification={seen['verification']}"
    )

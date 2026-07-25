"""The memory hooks, driven through a real run.

`tests/test_memory.py` exercises the bridge in isolation. This file exercises
the *wiring*: that the kernel calls it at the right moments, in the right order,
and that a misbehaving memory cannot take a run down with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from orkestra.kernel import scheduler as scheduler_module
from orkestra.schemas.common import RunState, TaskKind
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e


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

    def brief_context(self, **_: Any) -> str:
        self._note("brief_context")
        return ""

    def preflight_warning(self, **_: Any) -> str:
        self._note("preflight_warning")
        return ""

    def record_verification(self, **_: Any) -> None:
        self._note("record_verification")

    def record_review(self, **_: Any) -> None:
        self._note("record_review")

    def record_integration(self, **_: Any) -> None:
        self._note("record_integration")

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
        "brief_context",
        "record_verification",
        "record_review",
        "record_integration",
        "record_run_completed",
    ):
        assert expected in memory.calls, f"{expected} was never recorded"


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
        # The shell concatenates `MARK""ER` into `MARKER`, which the command
        # string therefore never literally contains.
        marker = "MARKER9c1f"
        command = "sh -c 'echo MARK\"\"ER9c1f >&2; exit 1'"
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

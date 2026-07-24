"""Unit tests: transition tables and retry/backoff policy."""

from __future__ import annotations

from orkestra.kernel.retry import BackoffPolicy, next_agent
from orkestra.kernel.states import (
    RUN_TRANSITIONS,
    TASK_TRANSITIONS,
    can_transition_run,
    can_transition_task,
)
from orkestra.schemas.agent import ErrorKind
from orkestra.schemas.common import RunState, TaskState


class TestTransitionTables:
    def test_every_state_has_an_entry(self) -> None:
        assert set(TASK_TRANSITIONS) == set(TaskState)
        assert set(RUN_TRANSITIONS) == set(RunState)

    def test_terminal_states_have_no_exits(self) -> None:
        assert not TASK_TRANSITIONS[TaskState.DONE]
        assert not TASK_TRANSITIONS[TaskState.CANCELLED]
        assert not RUN_TRANSITIONS[RunState.COMPLETE]
        assert not RUN_TRANSITIONS[RunState.CANCELLED]

    def test_pipeline_happy_path_is_legal(self) -> None:
        chain = [
            TaskState.PENDING, TaskState.READY, TaskState.RUNNING,
            TaskState.VERIFYING, TaskState.REVIEWING, TaskState.INTEGRATING,
            TaskState.DONE,
        ]
        for current, upcoming in zip(chain, chain[1:], strict=False):
            assert can_transition_task(current, upcoming), f"{current} -> {upcoming}"

    def test_illegal_shortcuts_rejected(self) -> None:
        assert not can_transition_task(TaskState.PENDING, TaskState.DONE)
        assert not can_transition_task(TaskState.DONE, TaskState.READY)
        assert not can_transition_run(RunState.CREATED, RunState.COMPLETE)

    def test_recovery_paths(self) -> None:
        assert can_transition_task(TaskState.BLOCKED, TaskState.READY)
        assert can_transition_task(TaskState.FAILED, TaskState.READY)
        assert can_transition_run(RunState.PAUSED, RunState.RUNNING)
        assert can_transition_run(RunState.WAITING_HUMAN, RunState.RUNNING)


class TestBackoff:
    def test_exponential_with_cap(self) -> None:
        policy = BackoffPolicy(base_s=5, factor=2, max_s=40)
        delays = [policy.delay(i, ErrorKind.CRASH) for i in range(5)]
        assert delays == [5, 10, 20, 40, 40]

    def test_rate_limit_uses_longer_base(self) -> None:
        policy = BackoffPolicy()
        assert policy.delay(0, ErrorKind.RATE_LIMIT) > policy.delay(0, ErrorKind.CRASH)


class TestNextAgent:
    def test_chain_order(self) -> None:
        assert next_agent([], "a", ["b", "c"]) == "a"
        assert next_agent(["a"], "a", ["b", "c"]) == "b"
        assert next_agent(["a", "b"], "a", ["b", "c"]) == "c"
        assert next_agent(["a", "b", "c"], "a", ["b", "c"]) is None

    def test_primary_not_duplicated_in_fallbacks(self) -> None:
        assert next_agent(["a"], "a", ["a", "b"]) == "b"

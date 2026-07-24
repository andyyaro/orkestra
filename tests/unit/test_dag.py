"""Unit tests: task DAG validation, cycle detection, ready frontier."""

from __future__ import annotations

import pytest

from orkestra.errors import DagError
from orkestra.kernel.dag import TaskDag
from orkestra.schemas.common import TaskState


def make_dag() -> TaskDag:
    #   a -> b -> d
    #   a -> c -> d
    return TaskDag(
        deps={"b": ["a"], "c": ["a"], "d": ["b", "c"]},
        all_keys=["a", "b", "c", "d"],
    )


class TestValidation:
    def test_cycle_detected(self) -> None:
        with pytest.raises(DagError, match="cycle"):
            TaskDag(deps={"a": ["b"], "b": ["a"]}, all_keys=["a", "b"])

    def test_self_dependency_detected(self) -> None:
        with pytest.raises(DagError, match="depends on itself"):
            TaskDag(deps={"a": ["a"]}, all_keys=["a"])

    def test_unknown_dependency_detected(self) -> None:
        with pytest.raises(DagError, match="unknown task"):
            TaskDag(deps={"a": ["ghost"]}, all_keys=["a"])

    def test_duplicate_keys_detected(self) -> None:
        with pytest.raises(DagError, match="duplicate"):
            TaskDag(deps={}, all_keys=["a", "a"])

    def test_long_chain_is_fine(self) -> None:
        keys = [f"t{i}" for i in range(200)]
        deps = {keys[i]: [keys[i - 1]] for i in range(1, 200)}
        dag = TaskDag(deps=deps, all_keys=keys)
        assert dag.topological_order()[0] == "t0"


class TestScheduling:
    def test_ready_frontier_start(self) -> None:
        dag = make_dag()
        states = dict.fromkeys("abcd", TaskState.PENDING)
        assert dag.ready_keys(states) == ["a"]

    def test_parallel_frontier_after_a(self) -> None:
        dag = make_dag()
        states = {"a": TaskState.DONE, "b": TaskState.PENDING,
                  "c": TaskState.PENDING, "d": TaskState.PENDING}
        assert dag.ready_keys(states) == ["b", "c"]

    def test_join_waits_for_all(self) -> None:
        dag = make_dag()
        states = {"a": TaskState.DONE, "b": TaskState.DONE,
                  "c": TaskState.RUNNING, "d": TaskState.PENDING}
        assert dag.ready_keys(states) == []

    def test_complete(self) -> None:
        dag = make_dag()
        assert dag.is_complete(dict.fromkeys("abcd", TaskState.DONE))
        assert not dag.is_complete({**dict.fromkeys("abcd", TaskState.DONE),
                                    "d": TaskState.RUNNING})

    def test_stuck_when_dependency_failed(self) -> None:
        dag = make_dag()
        states = {"a": TaskState.FAILED, "b": TaskState.PENDING,
                  "c": TaskState.PENDING, "d": TaskState.PENDING}
        assert dag.is_stuck(states)

    def test_not_stuck_while_running(self) -> None:
        dag = make_dag()
        states = {"a": TaskState.RUNNING, "b": TaskState.PENDING,
                  "c": TaskState.PENDING, "d": TaskState.PENDING}
        assert not dag.is_stuck(states)

    def test_downstream(self) -> None:
        dag = make_dag()
        assert dag.downstream_of("a") == {"b", "c", "d"}
        assert dag.downstream_of("d") == set()

"""Legal state transition tables (enforced additionally by Store guards)."""

from __future__ import annotations

from orkestra.schemas.common import RunState, TaskState

TASK_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY, TaskState.CANCELLED}),
    TaskState.READY: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.BLOCKED}),
    TaskState.RUNNING: frozenset(
        {TaskState.VERIFYING, TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED,
         TaskState.FAILED}
    ),
    TaskState.VERIFYING: frozenset(
        {TaskState.REVIEWING, TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED,
         TaskState.DONE}
    ),
    TaskState.REVIEWING: frozenset(
        {TaskState.INTEGRATING, TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED}
    ),
    TaskState.INTEGRATING: frozenset(
        {TaskState.DONE, TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED}
    ),
    TaskState.BLOCKED: frozenset({TaskState.READY, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.DONE: frozenset(),
    TaskState.FAILED: frozenset({TaskState.READY}),
    TaskState.CANCELLED: frozenset(),
}

RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.ANALYZING, RunState.CANCELLED}),
    RunState.ANALYZING: frozenset(
        {RunState.PROBING, RunState.PLANNING, RunState.FAILED, RunState.CANCELLED,
         RunState.WAITING_HUMAN}
    ),
    RunState.PROBING: frozenset(
        {RunState.PLANNING, RunState.FAILED, RunState.CANCELLED, RunState.WAITING_HUMAN}
    ),
    RunState.PLANNING: frozenset(
        {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED, RunState.WAITING_HUMAN}
    ),
    RunState.RUNNING: frozenset(
        {RunState.PAUSED, RunState.WAITING_HUMAN, RunState.COMPLETE, RunState.FAILED,
         RunState.CANCELLED}
    ),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.WAITING_HUMAN: frozenset(
        {RunState.RUNNING, RunState.PLANNING, RunState.FAILED, RunState.CANCELLED}
    ),
    RunState.COMPLETE: frozenset(),
    RunState.FAILED: frozenset({RunState.RUNNING}),  # resume after fix
    RunState.CANCELLED: frozenset(),
}


def can_transition_task(current: TaskState, new: TaskState) -> bool:
    return new in TASK_TRANSITIONS[current]


def can_transition_run(current: RunState, new: RunState) -> bool:
    return new in RUN_TRANSITIONS[current]

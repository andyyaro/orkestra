"""Shared enums and helpers for schema models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


def utc_now() -> datetime:
    """Timezone-aware current time (single source of truth)."""
    return datetime.now(UTC)


class RunState(StrEnum):
    """Lifecycle of a project run."""

    CREATED = "created"
    ANALYZING = "analyzing"
    PROBING = "probing"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_HUMAN = "waiting_human"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState(StrEnum):
    """Lifecycle of a task inside the DAG."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    INTEGRATING = "integrating"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptState(StrEnum):
    """Lifecycle of a single agent attempt at a task."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskKind(StrEnum):
    """What kind of work a task represents (drives policy + capability match)."""

    RESEARCH = "research"
    PLAN = "plan"
    IMPLEMENT = "implement"
    TEST = "test"
    REVIEW = "review"
    DEBUG = "debug"
    INTEGRATE = "integrate"
    DOCUMENT = "document"

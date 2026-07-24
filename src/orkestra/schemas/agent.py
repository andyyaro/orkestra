"""Contracts between the kernel and agent adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from orkestra.schemas.common import utc_now


class ErrorKind(StrEnum):
    """Closed taxonomy for normalized agent failures."""

    NONE = "none"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CRASH = "crash"
    INVALID_OUTPUT = "invalid_output"
    POLICY = "policy"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ResultStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class EventKind(StrEnum):
    """Normalized agent event stream vocabulary."""

    STARTED = "started"
    TEXT = "text"
    THINKING = "thinking"
    TOOL = "tool"
    USAGE = "usage"
    WARNING = "warning"
    ERROR = "error"
    COMPLETED = "completed"
    RAW = "raw"


class AgentEvent(BaseModel):
    """One normalized event emitted by an adapter during a run."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    ts: datetime = Field(default_factory=utc_now)
    kind: EventKind
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Token/cost usage metadata (all fields optional-by-zero)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_cost_usd: float | None = None

    def merged(self, other: Usage) -> Usage:
        cost: float | None
        if self.total_cost_usd is None and other.total_cost_usd is None:
            cost = None
        else:
            cost = (self.total_cost_usd or 0.0) + (other.total_cost_usd or 0.0)
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            total_cost_usd=cost,
        )


class SessionRef(BaseModel):
    """Resume handle for an agent session (cwd-scoped for all vendors)."""

    session_id: str
    cwd: str


class AuthStatus(BaseModel):
    """Result of a non-invasive auth readiness check."""

    ready: bool
    detail: str = ""


class AgentResult(BaseModel):
    """Structured final result of one agent attempt."""

    schema_version: int = 1
    status: ResultStatus
    error_kind: ErrorKind = ErrorKind.NONE
    error_detail: str = ""
    final_text: str = ""
    structured: dict[str, Any] | None = None
    session: SessionRef | None = None
    usage: Usage = Field(default_factory=Usage)
    exit_code: int | None = None
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is ResultStatus.OK

"""Adapter contract.

An adapter is a pure translator between Orkestra's task brief and one
agent CLI: it builds an argv (never a shell string), parses the CLI's
output stream into normalized ``AgentEvent`` objects, and produces a
structured ``AgentResult``. Process supervision (spawn, stream, timeout,
cancel, kill) lives in :mod:`orkestra.adapters.runner`, shared by all
adapters.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orkestra.schemas.agent import AgentEvent, AgentResult, AuthStatus

if TYPE_CHECKING:
    from orkestra.schemas.task import TaskBrief


@dataclass(frozen=True)
class AdapterInfo:
    """Detection result for one adapter."""

    adapter_id: str
    available: bool
    version: str = ""
    executable: str = ""
    detail: str = ""
    features: frozenset[str] = frozenset()
    """Feature flags, e.g. {"structured_output", "resume", "structured_director"}."""


@dataclass(frozen=True)
class InvocationSpec:
    """Everything the runner needs to launch one attempt."""

    argv: list[str]
    cwd: str
    env_extra: dict[str, str] = field(default_factory=dict)
    stdin_data: bytes | None = None
    timeout_s: int = 1800


class StreamParser(ABC):
    """Incremental parser turning raw CLI output lines into events."""

    @abstractmethod
    def feed_line(self, line: str, *, is_stderr: bool) -> Iterable[AgentEvent]:
        """Parse one output line into zero or more normalized events."""

    @abstractmethod
    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        """Produce the final structured result after process exit."""


class AgentAdapter(ABC):
    """Stable contract implemented by all adapters (first- and third-party)."""

    adapter_id: str
    executable: str

    @abstractmethod
    async def detect(self) -> AdapterInfo:
        """Report availability, version, and feature flags. Never raises."""

    @abstractmethod
    async def check_auth(self) -> AuthStatus:
        """Non-invasive auth readiness check (never reads credential stores)."""

    @abstractmethod
    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        """Translate a task brief into a concrete CLI invocation."""

    @abstractmethod
    def make_parser(self, brief: TaskBrief) -> StreamParser:
        """Fresh parser for one attempt's output stream."""

    def which(self) -> str | None:
        """Locate the executable on PATH (helper for detect())."""
        return shutil.which(self.executable)

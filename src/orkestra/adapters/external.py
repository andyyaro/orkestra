"""External-command adapter — the third-party integration surface.

Protocol ``orkestra-jsonl/1`` (documented in docs/adapters/PROTOCOL.md):
the command receives the task brief as JSON on stdin and emits JSONL on
stdout:

    {"type": "started", "session_id": "..."}        (optional)
    {"type": "text", "text": "..."}                  (repeatable)
    {"type": "tool", "name": "..."}                  (repeatable)
    {"type": "result", "status": "ok"|"error", "final_text": "...",
     "structured": {...}|null, "error_kind": "...", "error_detail": "...",
     "usage": {"input_tokens": 0, "output_tokens": 0}}   (terminal, required)

No dynamic code loading: the command is declared explicitly in project
configuration (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from orkestra.adapters.base import AdapterInfo, AgentAdapter, InvocationSpec, StreamParser
from orkestra.adapters.jsonl import try_parse_json
from orkestra.adapters.runner import run_capture
from orkestra.schemas.agent import (
    AgentEvent,
    AgentResult,
    AuthStatus,
    ErrorKind,
    EventKind,
    ResultStatus,
    SessionRef,
    Usage,
)
from orkestra.schemas.task import TaskBrief

PROTOCOL_VERSION = "orkestra-jsonl/1"


class ExternalParser(StreamParser):
    def __init__(self) -> None:
        self.final: dict[str, Any] | None = None
        self.session_id = ""
        self.stderr_tail: list[str] = []

    def feed_line(self, line: str, *, is_stderr: bool) -> Iterable[AgentEvent]:
        if is_stderr:
            if line.strip():
                self.stderr_tail = [*self.stderr_tail, line][-20:]
            return
        obj = try_parse_json(line)
        if obj is None:
            if line.strip():
                yield AgentEvent(kind=EventKind.RAW, text=line[:2000])
            return
        kind = obj.get("type")
        if kind == "started":
            self.session_id = str(obj.get("session_id") or "")
            yield AgentEvent(
                kind=EventKind.STARTED,
                text="external agent started",
                data={"session_id": self.session_id},
            )
        elif kind == "text":
            yield AgentEvent(kind=EventKind.TEXT, text=str(obj.get("text", ""))[:4000])
        elif kind == "tool":
            yield AgentEvent(kind=EventKind.TOOL, text=str(obj.get("name", "tool")))
        elif kind == "result":
            self.final = obj
        else:
            yield AgentEvent(kind=EventKind.RAW, text=line[:1000])

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        if self.final is None:
            return AgentResult(
                status=ResultStatus.ERROR,
                error_kind=ErrorKind.INVALID_OUTPUT if exit_code == 0 else ErrorKind.CRASH,
                error_detail=("\n".join(self.stderr_tail) or "no result event received")[:2000],
                exit_code=exit_code,
                duration_s=duration_s,
            )
        usage_raw = self.final.get("usage") or {}
        status_ok = self.final.get("status") == "ok" and exit_code == 0
        raw_error_kind = str(self.final.get("error_kind") or "unknown")
        try:
            error_kind = ErrorKind(raw_error_kind) if not status_ok else ErrorKind.NONE
        except ValueError:
            error_kind = ErrorKind.UNKNOWN
        structured = self.final.get("structured")
        return AgentResult(
            status=ResultStatus.OK if status_ok else ResultStatus.ERROR,
            error_kind=error_kind,
            error_detail=str(self.final.get("error_detail") or "")[:2000],
            final_text=str(self.final.get("final_text") or ""),
            structured=structured if isinstance(structured, dict) else None,
            session=(SessionRef(session_id=self.session_id, cwd=cwd) if self.session_id else None),
            usage=Usage(
                input_tokens=int(usage_raw.get("input_tokens") or 0),
                output_tokens=int(usage_raw.get("output_tokens") or 0),
            ),
            exit_code=exit_code,
            duration_s=duration_s,
        )


class ExternalAdapter(AgentAdapter):
    adapter_id = "external"

    def __init__(self, command: list[str], name: str = "external") -> None:
        if not command:
            msg = "external adapter requires a non-empty command"
            raise ValueError(msg)
        self.command = list(command)
        self.executable = command[0]
        self.name = name

    async def detect(self) -> AdapterInfo:
        code, out, err = await run_capture([*self.command, "--orkestra-detect"])
        if code is None:
            return AdapterInfo(
                self.adapter_id, available=False, detail=f"command failed: {err[:200]}"
            )
        version = ""
        protocol_ok = False
        for line in out.splitlines():
            obj = try_parse_json(line)
            if obj and obj.get("protocol") == PROTOCOL_VERSION:
                protocol_ok = True
                version = str(obj.get("version") or "")
        if code != 0 or not protocol_ok:
            return AdapterInfo(
                self.adapter_id,
                available=False,
                executable=self.executable,
                detail=f"detect handshake failed (exit {code}); expected "
                f'{{"protocol": "{PROTOCOL_VERSION}"}} on stdout',
            )
        return AdapterInfo(
            self.adapter_id,
            available=True,
            version=version,
            executable=self.executable,
            features=frozenset({"structured_output", "structured_director"}),
        )

    async def check_auth(self) -> AuthStatus:
        info = await self.detect()
        return AuthStatus(ready=info.available, detail=info.detail)

    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        return InvocationSpec(
            argv=list(self.command),
            cwd=brief.cwd,
            stdin_data=brief.model_dump_json().encode("utf-8"),
            timeout_s=brief.timeout_s,
        )

    def make_parser(self, brief: TaskBrief) -> StreamParser:
        return ExternalParser()

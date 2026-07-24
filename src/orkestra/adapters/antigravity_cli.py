"""Antigravity CLI adapter (`agy`) — first-party Google adapter.

Surface verified live 2026-07-24 against agy 1.1.6 (samples/):

- ``agy -p --output-format stream-json`` emits JSONL: ``init``
  (conversation_id, tools, permission_mode), ``step_update``
  (``step_type: agent_response`` carries ``text_delta`` + usage), and a
  terminal ``result`` envelope (``conversation_id``, ``status``,
  ``response``, ``usage``).
- ``--output-format`` is accepted although undocumented in ``--help``;
  the parser therefore also handles plain-text output as a fallback.
- No schema-constrained output: structured requests use prompt-level
  JSON plus :func:`extract_json_object` with kernel-side repair retries.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from orkestra.adapters.base import AdapterInfo, AgentAdapter, InvocationSpec, StreamParser
from orkestra.adapters.jsonl import extract_json_object, try_parse_json
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


class AntigravityParser(StreamParser):
    def __init__(self, expect_structured: bool) -> None:
        self.expect_structured = expect_structured
        self.conversation_id = ""
        self.final: dict[str, Any] | None = None
        self.plain_lines: list[str] = []
        self.stderr_tail: list[str] = []

    def feed_line(self, line: str, *, is_stderr: bool) -> Iterable[AgentEvent]:
        if is_stderr:
            if line.strip():
                self.stderr_tail = [*self.stderr_tail, line][-20:]
            return
        obj = try_parse_json(line)
        if obj is None:
            # Plain-text fallback (older versions / flag removed upstream).
            self.plain_lines.append(line)
            if line.strip():
                yield AgentEvent(kind=EventKind.TEXT, text=line[:2000])
            return
        event = obj.get("event")
        if event == "init":
            init = obj.get("init") or {}
            self.conversation_id = str(obj.get("conversation_id") or "")
            yield AgentEvent(
                kind=EventKind.STARTED,
                text="antigravity session initialized",
                data={
                    "conversation_id": self.conversation_id,
                    "permission_mode": init.get("permission_mode", ""),
                },
            )
        elif event == "step_update":
            step = obj.get("step_update") or {}
            step_type = step.get("step_type")
            if step_type == "agent_response" and step.get("text_delta"):
                yield AgentEvent(kind=EventKind.TEXT, text=str(step["text_delta"])[:4000])
            elif step_type not in (None, "user_input", "checkpoint", "unknown"):
                yield AgentEvent(kind=EventKind.TOOL, text=str(step_type))
        elif event == "result":
            self.final = obj.get("result") or {}

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        stderr = "\n".join(self.stderr_tail)
        if self.final is not None:
            usage_raw = self.final.get("usage") or {}
            usage = Usage(
                input_tokens=int(usage_raw.get("input_tokens") or 0),
                output_tokens=int(usage_raw.get("output_tokens") or 0),
            )
            conversation_id = str(self.final.get("conversation_id") or self.conversation_id)
            status = str(self.final.get("status") or "")
            text = str(self.final.get("response") or "")
            ok = status.upper() == "SUCCESS" and (exit_code in (0, None))
            structured = extract_json_object(text) if self.expect_structured else None
            if ok and self.expect_structured and structured is None:
                return AgentResult(
                    status=ResultStatus.ERROR,
                    error_kind=ErrorKind.INVALID_OUTPUT,
                    error_detail="expected JSON in response, none found",
                    final_text=text,
                    exit_code=exit_code,
                    duration_s=duration_s,
                )
            return AgentResult(
                status=ResultStatus.OK if ok else ResultStatus.ERROR,
                error_kind=ErrorKind.NONE if ok else ErrorKind.UNKNOWN,
                error_detail="" if ok else f"status={status}",
                final_text=text,
                structured=structured,
                session=(
                    SessionRef(session_id=conversation_id, cwd=cwd) if conversation_id else None
                ),
                usage=usage,
                exit_code=exit_code,
                duration_s=duration_s,
            )
        # Plain-text fallback path.
        text = "\n".join(self.plain_lines).strip()
        lower = (stderr + text).lower()
        if exit_code == 0 and text:
            structured = extract_json_object(text) if self.expect_structured else None
            if self.expect_structured and structured is None:
                return AgentResult(
                    status=ResultStatus.ERROR,
                    error_kind=ErrorKind.INVALID_OUTPUT,
                    error_detail="expected JSON in response, none found",
                    final_text=text,
                    exit_code=exit_code,
                    duration_s=duration_s,
                )
            return AgentResult(
                status=ResultStatus.OK,
                final_text=text,
                structured=structured,
                exit_code=exit_code,
                duration_s=duration_s,
            )
        if "auth" in lower or "sign in" in lower or "log in" in lower:
            kind = ErrorKind.AUTH
        elif "rate limit" in lower or "quota" in lower:
            kind = ErrorKind.RATE_LIMIT
        else:
            kind = ErrorKind.CRASH if exit_code else ErrorKind.INVALID_OUTPUT
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=kind,
            error_detail=(stderr or text or f"exit {exit_code}")[:2000],
            exit_code=exit_code,
            duration_s=duration_s,
        )


class AntigravityCliAdapter(AgentAdapter):
    adapter_id = "antigravity-cli"
    executable = "agy"

    def __init__(self, model: str | None = None, autonomy: str = "safe") -> None:
        self.model = model
        self.autonomy = autonomy

    async def detect(self) -> AdapterInfo:
        path = self.which()
        if not path:
            return AdapterInfo(self.adapter_id, available=False, detail="`agy` not found on PATH")
        code, out, err = await run_capture([path, "--version"])
        if code != 0:
            return AdapterInfo(
                self.adapter_id,
                available=False,
                executable=path,
                detail=f"--version failed: {err.strip()[:200]}",
            )
        return AdapterInfo(
            self.adapter_id,
            available=True,
            version=out.strip(),
            executable=path,
            features=frozenset({"resume", "stream", "os_sandbox"}),
            detail=(
                "note: Antigravity ToS restricts third-party access to the "
                "service; Orkestra only launches the official binary under "
                "your own login — review antigravity.google/terms"
            ),
        )

    async def check_auth(self) -> AuthStatus:
        path = self.which()
        if not path:
            return AuthStatus(ready=False, detail="`agy` not found on PATH")
        # `agy models` succeeds only when authenticated and consumes no
        # model quota (verified locally 2026-07-24).
        code, out, err = await run_capture([path, "models"], timeout_s=30)
        if code == 0 and out.strip():
            return AuthStatus(ready=True, detail="authenticated (models listed)")
        return AuthStatus(
            ready=False,
            detail=(err or out).strip()[:200] or "run `agy` interactively to sign in",
        )

    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        timeout_arg = f"{max(brief.timeout_s, 60)}s"
        argv = [
            self.which() or self.executable,
            "-p",
            brief.instructions,
            "--output-format",
            "stream-json",
            "--print-timeout",
            timeout_arg,
        ]
        if self.autonomy == "unsafe-full":
            argv += ["--dangerously-skip-permissions"]
        elif brief.kind.value in ("research", "plan", "review"):
            argv += ["--mode", "plan"]
        else:
            argv += ["--mode", "accept-edits"]
        if self.model:
            argv += ["--model", self.model]
        if brief.resume_session_id:
            argv += ["--conversation", brief.resume_session_id]
        return InvocationSpec(argv=argv, cwd=brief.cwd, timeout_s=brief.timeout_s + 30)

    def make_parser(self, brief: TaskBrief) -> StreamParser:
        return AntigravityParser(expect_structured=brief.json_schema is not None)

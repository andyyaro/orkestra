"""Gemini CLI adapter (`gemini`) — non-default Google adapter.

Valid only for API-key / Vertex / Code Assist Standard-Enterprise auth;
consumer OAuth was migrated to Antigravity (see
docs/research/ANTIGRAVITY_CLI_RESEARCH.md). Auth-not-ready is exit 41
with a JSON error on stderr (verified locally, samples/).
"""

from __future__ import annotations

import os
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

_AUTH_EXIT = 41
_TURN_LIMIT_EXIT = 53


class GeminiParser(StreamParser):
    def __init__(self, expect_structured: bool) -> None:
        self.expect_structured = expect_structured
        self.session_id = ""
        self.final: dict[str, Any] | None = None
        self.error_obj: dict[str, Any] | None = None
        self.text_parts: list[str] = []
        self.stderr_tail: list[str] = []

    def feed_line(self, line: str, *, is_stderr: bool) -> Iterable[AgentEvent]:
        obj = try_parse_json(line)
        if is_stderr:
            if obj and "error" in obj:
                self.error_obj = obj
            elif line.strip():
                self.stderr_tail = (self.stderr_tail + [line])[-20:]
            return
        if obj is None:
            if line.strip():
                yield AgentEvent(kind=EventKind.RAW, text=line[:2000])
            return
        event_type = obj.get("type") or obj.get("event")
        if event_type == "init":
            self.session_id = str(obj.get("session_id") or obj.get("sessionId") or "")
            yield AgentEvent(kind=EventKind.STARTED, text="gemini session initialized",
                             data={"session_id": self.session_id})
        elif event_type == "message":
            content = str(obj.get("content") or obj.get("text") or "")
            if content and obj.get("role") != "user":
                self.text_parts.append(content)
                yield AgentEvent(kind=EventKind.TEXT, text=content[:4000])
        elif event_type == "tool_use":
            yield AgentEvent(kind=EventKind.TOOL, text=str(obj.get("name", "tool")))
        elif event_type == "error":
            self.error_obj = obj
            yield AgentEvent(kind=EventKind.ERROR, text=str(obj)[:1000])
        elif event_type == "result":
            self.final = obj
        elif "response" in obj:  # -o json single envelope on stdout
            self.final = obj

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        if exit_code == _AUTH_EXIT or (
            self.error_obj and (self.error_obj.get("error") or {}).get("code") == _AUTH_EXIT
        ):
            message = ""
            if self.error_obj:
                message = str((self.error_obj.get("error") or {}).get("message", ""))
            return AgentResult(
                status=ResultStatus.ERROR,
                error_kind=ErrorKind.AUTH,
                error_detail=message or "gemini authentication required (exit 41)",
                exit_code=exit_code,
                duration_s=duration_s,
            )
        text = ""
        usage = Usage()
        if self.final is not None:
            text = str(self.final.get("response") or "")
            stats = self.final.get("stats") or {}
            if isinstance(stats, dict):
                tokens = stats.get("tokens") or stats
                if isinstance(tokens, dict):
                    usage = Usage(
                        input_tokens=int(tokens.get("input") or tokens.get("input_tokens") or 0),
                        output_tokens=int(
                            tokens.get("output") or tokens.get("output_tokens") or 0
                        ),
                    )
        if not text:
            text = "\n".join(self.text_parts).strip()
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
                session=(
                    SessionRef(session_id=self.session_id, cwd=cwd)
                    if self.session_id
                    else None
                ),
                usage=usage,
                exit_code=exit_code,
                duration_s=duration_s,
            )
        detail = ""
        if self.error_obj:
            detail = str((self.error_obj.get("error") or {}).get("message") or self.error_obj)
        detail = detail or "\n".join(self.stderr_tail) or f"exit {exit_code}"
        lower = detail.lower()
        if "rate" in lower or "quota" in lower or "429" in lower:
            kind = ErrorKind.RATE_LIMIT
        elif exit_code == _TURN_LIMIT_EXIT:
            kind = ErrorKind.POLICY
        else:
            kind = ErrorKind.CRASH if exit_code else ErrorKind.INVALID_OUTPUT
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=kind,
            error_detail=detail[:2000],
            final_text=text,
            exit_code=exit_code,
            duration_s=duration_s,
        )


class GeminiCliAdapter(AgentAdapter):
    adapter_id = "gemini-cli"
    executable = "gemini"

    def __init__(self, model: str | None = None, autonomy: str = "safe") -> None:
        self.model = model
        self.autonomy = autonomy

    async def detect(self) -> AdapterInfo:
        path = self.which()
        if not path:
            return AdapterInfo(self.adapter_id, available=False,
                               detail="`gemini` not found on PATH")
        code, out, err = await run_capture([path, "--version"])
        if code != 0:
            return AdapterInfo(self.adapter_id, available=False, executable=path,
                               detail=f"--version failed: {err.strip()[:200]}")
        return AdapterInfo(
            self.adapter_id,
            available=True,
            version=out.strip(),
            executable=path,
            features=frozenset({"resume", "stream", "os_sandbox"}),
            detail=(
                "requires GEMINI_API_KEY / Vertex / Enterprise auth — consumer "
                "Google-account OAuth is served by antigravity-cli instead"
            ),
        )

    async def check_auth(self) -> AuthStatus:
        if not self.which():
            return AuthStatus(ready=False, detail="`gemini` not found on PATH")
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
            return AuthStatus(ready=True, detail="API key / Vertex environment configured")
        return AuthStatus(
            ready=False,
            detail=(
                "no GEMINI_API_KEY or Vertex configuration; individual Google "
                "OAuth is no longer served by gemini-cli — use antigravity-cli"
            ),
        )

    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        argv = [
            self.which() or self.executable,
            "-p", brief.instructions,
            "-o", "stream-json",
            "--skip-trust",
        ]
        if self.autonomy == "unsafe-full":
            argv += ["--approval-mode", "yolo"]
        elif brief.kind.value in ("research", "plan", "review"):
            argv += ["--approval-mode", "plan"]
        else:
            argv += ["--approval-mode", "auto_edit"]
        if self.model:
            argv += ["--model", self.model]
        if brief.resume_session_id:
            argv += ["--resume", brief.resume_session_id]
        env_extra = {}
        for key in ("GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT"):
            if key in os.environ:
                env_extra[key] = os.environ[key]
        return InvocationSpec(argv=argv, cwd=brief.cwd, env_extra=env_extra,
                              timeout_s=brief.timeout_s)

    def make_parser(self, brief: TaskBrief) -> StreamParser:
        return GeminiParser(expect_structured=brief.json_schema is not None)

"""Claude Code adapter (`claude`).

Surface verified 2026-07-24 against claude 2.1.219 (see
docs/research/AGENT_INTEGRATION_RESEARCH.md and samples/):

- ``claude -p --output-format stream-json --verbose`` emits JSONL:
  ``system/init``, ``assistant``/``user`` messages, ``system/api_retry``
  (rate-limit/auth categories), and a terminal ``type:"result"`` object
  with ``result``, ``session_id``, ``is_error``, ``usage``,
  ``total_cost_usd``.
- ``--json-schema`` yields ``structured_output`` in the result envelope.
"""

from __future__ import annotations

import json
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

_API_ERROR_TO_KIND = {
    "authentication_failed": ErrorKind.AUTH,
    "oauth_org_not_allowed": ErrorKind.AUTH,
    "billing_error": ErrorKind.AUTH,
    "rate_limit": ErrorKind.RATE_LIMIT,
    "overloaded": ErrorKind.RATE_LIMIT,
}


#: Phrases a headless agent produces when a permission prompt it cannot
#: answer blocks it (typically running commands, e.g. the project's tests).
_PERMISSION_MARKERS = (
    "permission to run",
    "don't have permission",
    "do not have permission",
    "requires permission",
    "permission denied by",
    "cannot run commands",
    "need approval to run",
    "asking for approval",
)


def _looks_permission_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _PERMISSION_MARKERS)


class ClaudeParser(StreamParser):
    def __init__(self) -> None:
        self.final: dict[str, Any] | None = None
        self.last_error_kind = ErrorKind.NONE
        self.stderr_tail: list[str] = []
        self.permission_blocked = False

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
        if kind == "system":
            subtype = obj.get("subtype")
            if subtype == "init":
                yield AgentEvent(
                    kind=EventKind.STARTED,
                    text="claude session initialized",
                    data={"session_id": obj.get("session_id", "")},
                )
            elif subtype == "api_retry":
                category = str(obj.get("error", "unknown"))
                self.last_error_kind = _API_ERROR_TO_KIND.get(category, ErrorKind.UNKNOWN)
                yield AgentEvent(
                    kind=EventKind.WARNING,
                    text=f"api retry ({category})",
                    data={"category": category},
                )
        elif kind == "assistant":
            message = obj.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict):
                    if block.get("type") == "text" and block.get("text"):
                        text = str(block["text"])
                        if _looks_permission_blocked(text):
                            self.permission_blocked = True
                            yield AgentEvent(
                                kind=EventKind.WARNING,
                                text=(
                                    "agent appears blocked by a permission prompt it "
                                    "cannot answer headlessly (e.g. running commands). "
                                    "Pre-approve the tools it needs in the vendor CLI's "
                                    "settings — see docs/TROUBLESHOOTING.md"
                                ),
                            )
                        yield AgentEvent(kind=EventKind.TEXT, text=text[:4000])
                    elif block.get("type") == "tool_use":
                        yield AgentEvent(
                            kind=EventKind.TOOL,
                            text=str(block.get("name", "tool")),
                        )
        elif kind == "result":
            self.final = obj

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        if self.final is not None:
            usage_raw = self.final.get("usage") or {}
            usage = Usage(
                input_tokens=int(usage_raw.get("input_tokens") or 0),
                output_tokens=int(usage_raw.get("output_tokens") or 0),
                cached_input_tokens=int(usage_raw.get("cache_read_input_tokens") or 0)
                + int(usage_raw.get("cache_creation_input_tokens") or 0),
                total_cost_usd=self.final.get("total_cost_usd"),
            )
            session_id = str(self.final.get("session_id") or "")
            structured = self.final.get("structured_output")
            is_error = bool(self.final.get("is_error"))
            error_kind = ErrorKind.NONE
            detail = ""
            if is_error:
                error_kind = (
                    self.last_error_kind
                    if self.last_error_kind is not ErrorKind.NONE
                    else ErrorKind.UNKNOWN
                )
                detail = str(self.final.get("subtype") or "error")
            return AgentResult(
                status=ResultStatus.ERROR if is_error else ResultStatus.OK,
                error_kind=error_kind,
                error_detail=detail,
                final_text=str(self.final.get("result") or ""),
                structured=structured if isinstance(structured, dict) else None,
                session=SessionRef(session_id=session_id, cwd=cwd) if session_id else None,
                usage=usage,
                exit_code=exit_code,
                duration_s=duration_s,
            )
        stderr = "\n".join(self.stderr_tail)
        lower = stderr.lower()
        if "log in" in lower or "authentication" in lower or "api key" in lower:
            kind = ErrorKind.AUTH
        elif self.last_error_kind is not ErrorKind.NONE:
            kind = self.last_error_kind
        else:
            kind = ErrorKind.CRASH if exit_code else ErrorKind.INVALID_OUTPUT
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=kind,
            error_detail=(stderr or "no result envelope received")[:2000],
            exit_code=exit_code,
            duration_s=duration_s,
        )


class ClaudeCodeAdapter(AgentAdapter):
    adapter_id = "claude-code"
    executable = "claude"

    def __init__(self, model: str | None = None, autonomy: str = "safe") -> None:
        self.model = model
        self.autonomy = autonomy

    async def detect(self) -> AdapterInfo:
        path = self.which()
        if not path:
            return AdapterInfo(
                self.adapter_id, available=False, detail="`claude` not found on PATH"
            )
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
            version=out.strip().split()[0] if out.strip() else "",
            executable=path,
            features=frozenset({"structured_output", "resume", "structured_director", "stream"}),
        )

    async def check_auth(self) -> AuthStatus:
        # `claude -p` with a trivial prompt would consume quota; instead rely
        # on detection plus the documented failure envelope at run time. A
        # cheap deterministic signal: `claude auth status` isn't universally
        # available, so report ready-if-installed with a caveat.
        info = await self.detect()
        if not info.available:
            return AuthStatus(ready=False, detail=info.detail)
        return AuthStatus(
            ready=True,
            detail="installed; auth verified lazily on first invocation",
        )

    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        argv = [
            self.which() or self.executable,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--setting-sources",
            "user",
        ]
        if self.autonomy == "unsafe-full":
            argv += ["--permission-mode", "bypassPermissions"]
        else:
            argv += ["--permission-mode", "acceptEdits"]
        if self.model:
            argv += ["--model", self.model]
        if brief.json_schema is not None:
            # --json-schema requires --output-format json; the single result
            # envelope is still parsed by ClaudeParser.
            argv[argv.index("stream-json")] = "json"
            argv.remove("--verbose")
            argv += ["--json-schema", json.dumps(brief.json_schema)]
        if brief.resume_session_id:
            argv += ["--resume", brief.resume_session_id]
        argv.append(brief.instructions)
        return InvocationSpec(argv=argv, cwd=brief.cwd, timeout_s=brief.timeout_s)

    def make_parser(self, brief: TaskBrief) -> StreamParser:
        return ClaudeParser()

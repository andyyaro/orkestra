"""Codex CLI adapter (`codex exec`).

Surface verified 2026-07-24 against codex-cli 0.144.4 (samples/):
JSONL events ``thread.started`` (thread_id), ``turn.started``,
``item.started/completed/failed``, ``turn.completed`` (usage), ``error``.
``--output-schema <file>`` constrains the final message.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
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


class CodexParser(StreamParser):
    def __init__(self, expect_structured: bool) -> None:
        self.expect_structured = expect_structured
        self.thread_id = ""
        self.final_text = ""
        self.usage = Usage()
        self.error_text = ""
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
        if kind == "thread.started":
            self.thread_id = str(obj.get("thread_id") or "")
            yield AgentEvent(
                kind=EventKind.STARTED,
                text="codex thread started",
                data={"thread_id": self.thread_id},
            )
        elif kind == "item.completed":
            item = obj.get("item") or {}
            item_type = item.get("type")
            if item_type == "agent_message":
                self.final_text = str(item.get("text") or "")
                yield AgentEvent(kind=EventKind.TEXT, text=self.final_text[:4000])
            elif item_type == "command_execution":
                yield AgentEvent(
                    kind=EventKind.TOOL, text=str(item.get("command", "command"))[:500]
                )
            elif item_type == "reasoning":
                yield AgentEvent(kind=EventKind.THINKING, text=str(item.get("text", ""))[:1000])
        elif kind == "turn.completed":
            usage_raw: dict[str, Any] = obj.get("usage") or {}
            self.usage = self.usage.merged(
                Usage(
                    input_tokens=int(usage_raw.get("input_tokens") or 0),
                    output_tokens=int(usage_raw.get("output_tokens") or 0),
                    cached_input_tokens=int(usage_raw.get("cached_input_tokens") or 0),
                )
            )
            yield AgentEvent(kind=EventKind.USAGE, data=dict(usage_raw))
        elif kind == "error":
            self.error_text = str(obj.get("message") or obj)[:2000]
            yield AgentEvent(kind=EventKind.ERROR, text=self.error_text)

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        stderr = "\n".join(self.stderr_tail)
        combined_error = (self.error_text + "\n" + stderr).lower()
        if exit_code == 0 and not self.error_text:
            structured = None
            if self.expect_structured:
                structured = extract_json_object(self.final_text)
                if structured is None:
                    return AgentResult(
                        status=ResultStatus.ERROR,
                        error_kind=ErrorKind.INVALID_OUTPUT,
                        error_detail="expected schema-constrained JSON, none found",
                        final_text=self.final_text,
                        exit_code=exit_code,
                        duration_s=duration_s,
                    )
            return AgentResult(
                status=ResultStatus.OK,
                final_text=self.final_text,
                structured=structured,
                session=(
                    SessionRef(session_id=self.thread_id, cwd=cwd) if self.thread_id else None
                ),
                usage=self.usage,
                exit_code=exit_code,
                duration_s=duration_s,
            )
        if "login" in combined_error or "auth" in combined_error:
            kind = ErrorKind.AUTH
        elif "rate limit" in combined_error or "429" in combined_error:
            kind = ErrorKind.RATE_LIMIT
        elif self.error_text:
            kind = ErrorKind.UNKNOWN
        else:
            kind = ErrorKind.CRASH
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=kind,
            error_detail=(self.error_text or stderr or f"exit {exit_code}")[:2000],
            final_text=self.final_text,
            usage=self.usage,
            exit_code=exit_code,
            duration_s=duration_s,
        )


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Transform a Pydantic JSON schema into OpenAI strict-mode form.

    Strict mode requires every object to list ALL properties in
    ``required`` and to set ``additionalProperties: false``; ``default``
    and ``title`` annotations are stripped (observed live 2026-07-24:
    codex rejects schemas whose ``required`` omits defaulted fields).
    """

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items() if k not in ("default", "title")}
            if out.get("type") == "object" and isinstance(out.get("properties"), dict):
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    from typing import cast

    return cast("dict[str, Any]", walk(schema))


class CodexCliAdapter(AgentAdapter):
    adapter_id = "codex-cli"
    executable = "codex"

    def __init__(self, model: str | None = None, autonomy: str = "safe") -> None:
        self.model = model
        self.autonomy = autonomy
        self._schema_dir = Path(tempfile.gettempdir())

    async def detect(self) -> AdapterInfo:
        path = self.which()
        if not path:
            return AdapterInfo(self.adapter_id, available=False, detail="`codex` not found on PATH")
        code, out, err = await run_capture([path, "--version"])
        if code != 0:
            return AdapterInfo(
                self.adapter_id,
                available=False,
                executable=path,
                detail=f"--version failed: {err.strip()[:200]}",
            )
        version = out.strip().split()[-1] if out.strip() else ""
        return AdapterInfo(
            self.adapter_id,
            available=True,
            version=version,
            executable=path,
            features=frozenset({"structured_output", "resume", "stream", "os_sandbox"}),
        )

    async def check_auth(self) -> AuthStatus:
        path = self.which()
        if not path:
            return AuthStatus(ready=False, detail="`codex` not found on PATH")
        code, out, err = await run_capture([path, "login", "status"])
        text = (out + err).strip()
        if code == 0 and "logged in" in text.lower():
            return AuthStatus(ready=True, detail=text[:200])
        return AuthStatus(ready=False, detail=text[:200] or "not logged in")

    def build_invocation(self, brief: TaskBrief) -> InvocationSpec:
        argv = [self.which() or self.executable, "exec", "--json", "--skip-git-repo-check"]
        if self.autonomy == "unsafe-full":
            argv += ["--sandbox", "danger-full-access"]
        elif brief.kind.value in ("research", "plan", "review"):
            argv += ["--sandbox", "read-only"]
        else:
            argv += ["--sandbox", "workspace-write"]
        if self.model:
            argv += ["--model", self.model]
        if brief.json_schema is not None:
            schema_file = self._schema_dir / f"orkestra-schema-{brief.task_id}.json"
            schema_file.write_text(
                json.dumps(to_strict_schema(brief.json_schema)), encoding="utf-8"
            )
            argv += ["--output-schema", str(schema_file)]
        if brief.resume_session_id:
            argv = [*argv[:2], "resume", brief.resume_session_id, *argv[2:]]
        argv.append(brief.instructions)
        return InvocationSpec(argv=argv, cwd=brief.cwd, timeout_s=brief.timeout_s)

    def make_parser(self, brief: TaskBrief) -> StreamParser:
        return CodexParser(expect_structured=brief.json_schema is not None)

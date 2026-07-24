"""Scripted fake agent — reference implementation of ``orkestra-jsonl/1``.

Run as ``python -m orkestra.adapters.fake_worker``. Reads the task brief
JSON on stdin, obeys ``FAKE:`` directives embedded in the instructions,
and emits protocol events on stdout. Used by tests, offline mode, and
as the example third-party adapter.

Directives (one per line, anywhere in the instructions):

    FAKE:write:<relpath>:<content>   write a file into the workspace
    FAKE:fail[:detail]               emit an error result
    FAKE:exit:<code>                 exit with a raw code (crash simulation)
    FAKE:sleep:<seconds>             sleep (timeout/cancel testing)
    FAKE:garbage                     print non-protocol garbage lines
    FAKE:silent                      produce no result event
    FAKE:reject[:reason]             review verdict approve=false
    FAKE:reject_once[:reason]        reject on first review, approve after
    FAKE:fail_if_agent:<name>        fail only when run as that agent
    FAKE:structured:<json>           emit this JSON as `structured`
    FAKE:text:<text>                 set the final text

Defaults when no directive matches: implement/test/debug/document tasks
write a marker file; review tasks approve; everything succeeds.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "orkestra-jsonl/1"
FAKE_VERSION = "1.0.0"


def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    if "--orkestra-detect" in argv:
        emit({"protocol": PROTOCOL_VERSION, "version": FAKE_VERSION, "name": "fake"})
        return 0
    agent_name = ""
    if "--agent-name" in argv:
        index = argv.index("--agent-name")
        if index + 1 < len(argv):
            agent_name = argv[index + 1]

    try:
        brief = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        emit(
            {
                "type": "result",
                "status": "error",
                "error_kind": "invalid_output",
                "error_detail": "fake worker received invalid brief JSON",
            }
        )
        return 1

    instructions: str = brief.get("instructions", "")
    kind: str = brief.get("kind", "implement")
    cwd = Path(brief.get("cwd", "."))
    wants_json = brief.get("json_schema") is not None

    emit({"type": "started", "session_id": f"fake-{brief.get('task_id', 'unknown')}"})
    if brief.get("resume_session_id"):
        emit({"type": "text", "text": f"RESUMED:{brief['resume_session_id']}"})

    final_text = f"fake agent completed {kind} task"
    structured: dict[str, Any] | None = None
    status = "ok"
    error_kind = "none"
    error_detail = ""

    directives = [
        line.strip()[5:] for line in instructions.splitlines() if line.strip().startswith("FAKE:")
    ]
    wrote_something = False
    for directive in directives:
        parts = directive.split(":", 2)
        op = parts[0]
        if op == "sleep" and len(parts) > 1:
            time.sleep(float(parts[1]))
        elif op == "write" and len(parts) == 3:
            target = (cwd / parts[1]).resolve()
            if not target.is_relative_to(cwd.resolve()):
                status, error_kind = "error", "policy"
                error_detail = f"refusing to write outside workspace: {parts[1]}"
                break
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(parts[2] + "\n", encoding="utf-8")
            emit({"type": "tool", "name": f"write:{parts[1]}"})
            wrote_something = True
        elif op == "fail":
            status, error_kind = "error", "unknown"
            error_detail = parts[1] if len(parts) > 1 else "scripted failure"
        elif op == "exit" and len(parts) > 1:
            emit({"type": "text", "text": "about to crash"})
            return int(parts[1])
        elif op == "garbage":
            sys.stdout.write("this is not JSON at all\n{broken json\n")
            sys.stdout.flush()
        elif op == "silent":
            return 0
        elif op == "fail_if_agent" and len(parts) > 1:
            # Scoped to implementer-style attempts; review behavior is
            # scripted separately via reject/reject_once/silent.
            if agent_name == parts[1] and kind != "review":
                status, error_kind = "error", "crash"
                error_detail = f"scripted failure for agent {agent_name}"
                break
        elif op == "reject_once":
            if kind != "review":
                continue  # directive only affects the reviewer role
            reason = parts[1] if len(parts) > 1 else "scripted first-pass rejection"
            marker = cwd / ".fake-reject-done"
            if marker.exists():
                structured = {
                    "schema_version": 1,
                    "approve": True,
                    "findings": [],
                    "required_changes": [],
                    "severity": "none",
                }
            else:
                marker.write_text("rejected once\n", encoding="utf-8")
                structured = {
                    "schema_version": 1,
                    "approve": False,
                    "findings": [reason],
                    "required_changes": [reason],
                    "severity": "medium",
                }
            final_text = json.dumps(structured)
        elif op == "reject":
            reason = parts[1] if len(parts) > 1 else "scripted rejection"
            structured = {
                "schema_version": 1,
                "approve": False,
                "findings": [reason],
                "required_changes": [reason],
                "severity": "medium",
            }
            final_text = json.dumps(structured)
        elif op == "structured" and len(parts) > 1:
            structured = json.loads(":".join(parts[1:]))
            final_text = json.dumps(structured)
        elif op == "text" and len(parts) > 1:
            final_text = ":".join(parts[1:])

    if status == "ok" and structured is None and wants_json:
        if kind == "review":
            structured = {
                "schema_version": 1,
                "approve": True,
                "findings": [],
                "required_changes": [],
                "severity": "none",
            }
        else:
            structured = {"note": final_text}
        final_text = json.dumps(structured)

    if (
        status == "ok"
        and not wrote_something
        and not directives
        and kind in ("implement", "test", "debug", "document")
        and brief.get("task_id")
    ):
        marker = cwd / f"fake-{brief['task_id']}.txt"
        marker.write_text(f"work by fake agent for {brief.get('title', '')}\n", encoding="utf-8")
        emit({"type": "tool", "name": f"write:{marker.name}"})

    emit({"type": "text", "text": final_text})
    emit(
        {
            "type": "result",
            "status": status,
            "final_text": final_text,
            "structured": structured,
            "error_kind": error_kind,
            "error_detail": error_detail,
            "usage": {"input_tokens": len(instructions) // 4, "output_tokens": 20},
        }
    )
    return 0  # protocol errors are reported in-band via the result event


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

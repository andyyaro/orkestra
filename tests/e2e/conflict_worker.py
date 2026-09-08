"""Scripted agent (``orkestra-jsonl/1``) that reproduces the work-loss path.

Two tasks share one file. The ``first`` task writes it and integrates. The
``second`` task writes a conflicting version, then blocks until ``first``
has actually landed on the run's integration branch, so its own merge is
guaranteed to conflict. Its retry (a fresh worktree off the new integration
head) writes nothing at all - which is the shape the kernel used to score as
success.

Ordering is observed from Git, not from a sleep: the wait ends only when
the shared file is readable on the integration branch.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = "orkestra-jsonl/1"
SHARED = "shared.txt"
WAIT_TIMEOUT_S = 120.0


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def state_dir(argv: list[str]) -> Path:
    path = Path(argv[argv.index("--state-dir") + 1])
    path.mkdir(parents=True, exist_ok=True)
    return path


def integration_has_shared(root: Path, run_id: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"ork/{run_id}/integration:{SHARED}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def bump_attempts(counter: Path) -> int:
    previous = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
    counter.write_text(str(previous + 1), encoding="utf-8")
    return previous


def main(argv: list[str]) -> int:
    if "--orkestra-detect" in argv:
        emit({"protocol": PROTOCOL_VERSION, "version": "1.0.0", "name": "conflict-worker"})
        return 0

    brief = json.loads(sys.stdin.read() or "{}")
    kind = str(brief.get("kind", "implement"))
    title = str(brief.get("title", ""))
    run_id = str(brief.get("run_id", ""))
    cwd = Path(brief.get("cwd", "."))
    emit({"type": "started", "session_id": f"conflict-{brief.get('task_id', '')}"})

    structured: dict | None = None
    error_detail = ""

    if kind == "review":
        structured = {
            "schema_version": 1,
            "approve": True,
            "findings": [],
            "required_changes": [],
            "severity": "none",
        }
    elif title == "first":
        (cwd / SHARED).write_text("one\n", encoding="utf-8")
        emit({"type": "tool", "name": f"write:{SHARED}"})
    elif title == "second":
        attempts = bump_attempts(state_dir(argv) / "second-attempts")
        if attempts == 0:
            (cwd / SHARED).write_text("two\n", encoding="utf-8")
            emit({"type": "tool", "name": f"write:{SHARED}"})
            # <root>/.orkestra/worktrees/<dir> -> <root>
            root = cwd.parents[2]
            deadline = time.monotonic() + WAIT_TIMEOUT_S
            while not integration_has_shared(root, run_id):
                if time.monotonic() > deadline:
                    error_detail = "timed out waiting for the first task to integrate"
                    break
                time.sleep(0.05)
        else:
            # The retry produces no file changes whatsoever.
            emit({"type": "text", "text": "nothing left to do"})

    final_text = json.dumps(structured) if structured else f"scripted {kind} attempt finished"
    emit({"type": "text", "text": final_text})
    emit(
        {
            "type": "result",
            "status": "error" if error_detail else "ok",
            "final_text": final_text,
            "structured": structured,
            "error_kind": "unknown" if error_detail else "none",
            "error_detail": error_detail,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

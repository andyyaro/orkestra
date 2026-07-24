"""Shared subprocess runner for all adapters.

Guarantees: argv execution only (no shell), allowlisted environment,
process-group kill on timeout/cancel, bounded line lengths, and a
result even when the CLI produces garbage.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from orkestra.schemas.agent import (
    AgentEvent,
    AgentResult,
    ErrorKind,
    EventKind,
    ResultStatus,
)
from orkestra.verify.runner import subprocess_env

if TYPE_CHECKING:
    from orkestra.adapters.base import InvocationSpec, StreamParser

_MAX_LINE_BYTES = 1_000_000
_KILL_GRACE_S = 5.0

EventCallback = Callable[[AgentEvent], None]


async def _pump(
    stream: asyncio.StreamReader,
    parser: StreamParser,
    on_event: EventCallback,
    *,
    is_stderr: bool,
) -> None:
    while True:
        try:
            line_bytes = await stream.readline()
        except (ValueError, asyncio.LimitOverrunError):
            # Line exceeded the buffer limit: drain defensively and note it.
            on_event(
                AgentEvent(
                    kind=EventKind.WARNING,
                    text="output line exceeded limit and was truncated",
                )
            )
            continue
        if not line_bytes:
            return
        line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
        for event in parser.feed_line(line, is_stderr=is_stderr):
            on_event(event)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the whole process group, then SIGKILL after a grace period."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE_S)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        await proc.wait()


async def run_invocation(
    spec: InvocationSpec,
    parser: StreamParser,
    on_event: EventCallback,
    cancel_event: asyncio.Event | None = None,
) -> AgentResult:
    """Run one adapter invocation to completion, timeout, or cancellation."""
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *spec.argv,
            cwd=spec.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(spec.env_extra),
            start_new_session=True,
            limit=_MAX_LINE_BYTES,
        )
    except FileNotFoundError:
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=ErrorKind.UNAVAILABLE,
            error_detail=f"executable not found: {spec.argv[0]!r}",
        )
    except OSError as exc:
        return AgentResult(
            status=ResultStatus.ERROR,
            error_kind=ErrorKind.CRASH,
            error_detail=f"failed to spawn {spec.argv[0]!r}: {exc}",
        )

    on_event(AgentEvent(kind=EventKind.STARTED, text=" ".join(spec.argv[:3]) + " ..."))

    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    if spec.stdin_data:
        proc.stdin.write(spec.stdin_data)
        with contextlib.suppress(ConnectionResetError, BrokenPipeError):
            await proc.stdin.drain()
    proc.stdin.close()

    pumps = asyncio.gather(
        _pump(proc.stdout, parser, on_event, is_stderr=False),
        _pump(proc.stderr, parser, on_event, is_stderr=True),
    )

    timed_out = False
    cancelled = False
    wait_proc = asyncio.ensure_future(proc.wait())
    waiters: list[asyncio.Future[object]] = [wait_proc]
    cancel_waiter: asyncio.Future[object] | None = None
    if cancel_event is not None:
        cancel_waiter = asyncio.ensure_future(cancel_event.wait())
        waiters.append(cancel_waiter)
    try:
        done, _ = await asyncio.wait(
            waiters, timeout=spec.timeout_s, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            timed_out = True
        elif cancel_waiter is not None and cancel_waiter in done and wait_proc not in done:
            cancelled = True
    finally:
        if cancel_waiter is not None:
            cancel_waiter.cancel()
        if timed_out or cancelled:
            await _terminate(proc)
        await wait_proc
        with contextlib.suppress(Exception):
            await asyncio.wait_for(pumps, timeout=10)

    duration = time.monotonic() - start
    result = parser.result(proc.returncode, duration, spec.cwd)
    if timed_out:
        result = result.model_copy(
            update={
                "status": ResultStatus.ERROR,
                "error_kind": ErrorKind.TIMEOUT,
                "error_detail": f"timed out after {spec.timeout_s}s",
            }
        )
    elif cancelled:
        result = result.model_copy(
            update={
                "status": ResultStatus.ERROR,
                "error_kind": ErrorKind.CANCELLED,
                "error_detail": "cancelled by kernel",
            }
        )
    on_event(
        AgentEvent(
            kind=EventKind.COMPLETED,
            text=f"exit={proc.returncode} status={result.status.value}",
            data={"error_kind": result.error_kind.value},
        )
    )
    return result


async def run_capture(
    argv: list[str], timeout_s: float = 15.0, cwd: str | None = None
) -> tuple[int | None, str, str]:
    """Small helper for detection/version probes: run and capture output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(),
            start_new_session=True,
        )
    except FileNotFoundError:
        return None, "", "not found"
    except OSError as exc:
        return None, "", str(exc)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        await _terminate(proc)
        return None, "", f"timed out after {timeout_s}s"
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )

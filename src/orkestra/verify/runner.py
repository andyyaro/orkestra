"""Run project-defined verification commands and inspect exit codes.

Commands come only from user configuration (never from agents), are
parsed with ``shlex.split``, and run without a shell. An agent claiming
"tests pass" has no effect on this module (threat T14).
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

from orkestra.errors import VerificationError

_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER", "SHELL",
    "VIRTUAL_ENV", "PYTHONPATH", "NODE_PATH", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "CI",
)


def subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Allowlisted environment for verification/agent subprocesses (threat T3)."""
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    if extra:
        env.update(extra)
    return env


@dataclass
class CommandResult:
    command: str
    exit_code: int
    duration_s: float
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass
class VerificationOutcome:
    results: list[CommandResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def summary(self) -> str:
        if not self.results:
            return "no verification commands configured"
        lines = [
            f"{'PASS' if r.passed else 'FAIL'} (exit {r.exit_code}, "
            f"{r.duration_s:.1f}s): {r.command}"
            for r in self.results
        ]
        return "\n".join(lines)


async def run_verification(
    commands: list[str],
    cwd: Path,
    timeout_s: int = 900,
    env_extra: dict[str, str] | None = None,
) -> VerificationOutcome:
    """Run each command in order; stop at first failure."""
    outcome = VerificationOutcome()
    for command in commands:
        argv = shlex.split(command)
        if not argv:
            continue
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_env(env_extra),
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            msg = f"verification command not found: {argv[0]!r} (from {command!r})"
            raise VerificationError(msg) from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            outcome.results.append(
                CommandResult(
                    command=command,
                    exit_code=124,
                    duration_s=time.monotonic() - start,
                    stdout_tail="",
                    stderr_tail=f"timed out after {timeout_s}s",
                )
            )
            return outcome
        outcome.results.append(
            CommandResult(
                command=command,
                exit_code=proc.returncode if proc.returncode is not None else -1,
                duration_s=time.monotonic() - start,
                stdout_tail=stdout.decode(errors="replace")[-4000:],
                stderr_tail=stderr.decode(errors="replace")[-4000:],
            )
        )
        if not outcome.results[-1].passed:
            return outcome
    return outcome

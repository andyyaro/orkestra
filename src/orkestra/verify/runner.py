"""Run project-defined verification commands and inspect exit codes.

The authoritative gate is the user's ``[verify]`` commands. Plan-derived
acceptance entries may run *in addition*, but only after
``gate_command_problem`` confirms they are runnable argv commands -
LLM-suggested prose or shell one-liners are never exec'd. Everything is
parsed with ``shlex.split`` and runs without a shell. An agent claiming
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
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "USER",
    "SHELL",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "NODE_PATH",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "CI",
)


#: Characters that mean the string relies on a shell (pipes, globs,
#: substitution) or is prose (parentheses) - either way, not a gate.
_GATE_FORBIDDEN = set("|&;<>`$()*?{}[]\n")


def gate_command_problem(command: str, *, strict: bool = True) -> str | None:
    """Why this string cannot be exec'd as a verification gate (None = fine).

    ``strict=True`` (plan-derived entries): must be plain argv with a
    resolvable executable and no shell/prose syntax - anything else is
    dropped by the caller instead of exec'd or allowed to block a run.
    ``strict=False`` (user-authored [verify] commands): only checks the
    string parses and its executable exists, so a broken config is caught
    *before* an agent is dispatched, without second-guessing the user.
    """
    import shutil as _shutil

    stripped = command.strip()
    if not stripped:
        return "empty"
    if strict:
        bad = sorted({c for c in stripped if c in _GATE_FORBIDDEN})
        if bad:
            rendered = " ".join(repr(c) if c.isspace() else c for c in bad)
            return f"contains shell/prose syntax ({rendered}) - commands run without a shell"
        # Prose that merely *starts* with a real binary ("python3 -m pytest,
        # run from the repo root, exits 0") passes a naive check; commas and
        # sentence length are the reliable tells.
        if "," in stripped:
            return "reads as prose (contains a comma), not a command"
        if len(stripped) > 160:
            return "too long to be a command - reads as prose"
    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return f"cannot be parsed as a command ({exc})"
    if not argv:
        return "empty"
    if strict and len(argv) > 12:
        return "too many words to be a command - reads as prose"
    if _shutil.which(argv[0]) is None:
        return f"{argv[0]!r} is not an executable on PATH"
    return None


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

    def failure_detail(self, max_chars: int = 4000) -> str:
        """Output of the failing command(s) - what the user and the
        repairing agent need in order to understand the rejection."""
        chunks = []
        for r in self.results:
            if r.passed:
                continue
            body = "\n".join(part for part in (r.stdout_tail, r.stderr_tail) if part.strip())
            chunks.append(f"$ {r.command}   (exit {r.exit_code})\n{body or '(no output)'}")
        text = "\n\n".join(chunks)
        return text[:max_chars] + ("\n… (truncated)" if len(text) > max_chars else "")


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

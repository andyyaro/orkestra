"""Turn a verification outcome into rows that can be queried later.

A gate result is only useful as evidence if the facts that make it
falsifiable survive: which tree it ran against, which argv ran, which
executable that argv resolved to, what environment it saw, how long it
took, and whether anything ever proved the command read the tree the
result names. Rendering that into event prose throws all of it away.

This module builds the records; ``Store.add_verifications`` persists
them. It never runs a gate command.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from orkestra.verify.runner import CommandResult, VerificationOutcome

#: What tree the result is a statement about.
SCOPE_TASK = "task"
SCOPE_COMPOSITE = "composite"
SCOPE_ACCEPT = "accept"
SCOPE_BASELINE = "baseline"
SCOPES = frozenset({SCOPE_TASK, SCOPE_COMPOSITE, SCOPE_ACCEPT, SCOPE_BASELINE})

#: Whether anything proved the gate actually read the tree named above.
#: ``BINDING_NOT_CHECKED`` is the honest default and the only value this
#: module produces: nothing here measures binding. The binding canary that
#: produces ``proved``/``unbound`` is a separate component; when it exists
#: it passes its verdict into ``records_for_outcome(binding=...)``, which
#: is the seam it is expected to use. Never default this to ``proved``.
BINDING_PROVED = "proved"
BINDING_UNBOUND = "unbound"
BINDING_NOT_CHECKED = "not_checked"
BINDINGS = frozenset({BINDING_PROVED, BINDING_UNBOUND, BINDING_NOT_CHECKED})

#: Executables it is safe to ask for a version. An unknown gate entry may
#: be a project script that ignores its arguments, so probing it could run
#: the whole suite a second time; those get no version rather than a
#: surprise second gate run.
_VERSION_PROBE_SAFE = frozenset(
    {
        "bun",
        "cargo",
        "deno",
        "dotnet",
        "go",
        "gradle",
        "hatch",
        "java",
        "just",
        "make",
        "mvn",
        "mypy",
        "node",
        "npm",
        "npx",
        "php",
        "pnpm",
        "poetry",
        "pytest",
        "python",
        "python3",
        "rake",
        "rspec",
        "ruby",
        "ruff",
        "tox",
        "uv",
        "yarn",
    }
)

_VERSION_PROBE_TIMEOUT_S = 10


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def env_fingerprint(env: Mapping[str, str]) -> str:
    """Digest of the exact environment the gate was handed.

    Two results with different fingerprints were not produced under the
    same conditions, whatever their exit codes say. Hashed rather than
    stored verbatim because the environment carries paths and usernames.
    """
    rendered = "\n".join(f"{key}={env[key]}" for key in sorted(env))
    return _sha256(rendered)


def output_digest(result: CommandResult) -> str:
    """Digest of the captured output.

    ``CommandResult`` keeps only the last 4000 characters of each stream,
    so this identifies the captured tails, not the full output. Equal
    digests mean equal tails.
    """
    return _sha256(result.stdout_tail + "\0" + result.stderr_tail)


def resolve_executable(argv0: str, cwd: Path, env: Mapping[str, str]) -> str:
    """Absolute, symlink-resolved path of what *argv0* would execute.

    An exit code is a statement about a binary, not about a name:
    ``pytest`` means a different thing inside a virtualenv than outside
    one, and that difference is invisible in the command string.
    Returns "" when nothing resolves.
    """
    if not argv0:
        return ""
    if "/" in argv0:
        candidate = (cwd / argv0).expanduser()
        return str(candidate.resolve()) if candidate.exists() else ""
    found = shutil.which(argv0, path=env.get("PATH"))
    return str(Path(found).resolve()) if found else ""


async def probe_version(exe: str, argv0: str, cwd: Path, env: Mapping[str, str]) -> str:
    """First line of ``<exe> --version``, or "" when it cannot be asked.

    Only executables named in ``_VERSION_PROBE_SAFE`` are probed; see the
    note there for why an arbitrary gate entry is not.
    """
    if not exe or Path(argv0).name not in _VERSION_PROBE_SAFE:
        return ""
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--version",
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(env),
            start_new_session=True,
        )
    except OSError:
        return ""
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_VERSION_PROBE_TIMEOUT_S
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ""
    text = (stdout or stderr).decode(errors="replace").strip()
    return text.splitlines()[0][:200] if text else ""


@dataclass(frozen=True)
class VerificationRecord:
    """One gate command, one tree, one exit code, one duration."""

    run_id: str
    task_id: str | None
    scope: str
    commit_sha: str
    tree_sha: str
    command: str
    argv_json: str
    exe_realpath: str
    exe_version: str
    env_fingerprint: str
    exit_code: int
    duration_s: float
    output_digest: str
    binding: str

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            msg = f"unknown verification scope: {self.scope!r}"
            raise ValueError(msg)
        if self.binding not in BINDINGS:
            msg = f"unknown verification binding: {self.binding!r}"
            raise ValueError(msg)


async def records_for_outcome(
    outcome: VerificationOutcome,
    *,
    run_id: str,
    task_id: str | None,
    scope: str,
    commit_sha: str,
    tree_sha: str,
    cwd: Path,
    env: Mapping[str, str],
    binding: str = BINDING_NOT_CHECKED,
) -> list[VerificationRecord]:
    """One record per command that actually ran.

    ``run_verification`` stops at the first failure, so these are exactly
    the commands that were executed, never the ones that were configured.
    """
    fingerprint = env_fingerprint(env)
    resolved: dict[str, tuple[str, str]] = {}
    records = []
    for result in outcome.results:
        argv = shlex.split(result.command)
        argv0 = argv[0] if argv else ""
        if argv0 not in resolved:
            exe = resolve_executable(argv0, cwd, env)
            resolved[argv0] = (exe, await probe_version(exe, argv0, cwd, env))
        exe_realpath, exe_version = resolved[argv0]
        records.append(
            VerificationRecord(
                run_id=run_id,
                task_id=task_id,
                scope=scope,
                commit_sha=commit_sha,
                tree_sha=tree_sha,
                command=result.command,
                argv_json=json.dumps(argv),
                exe_realpath=exe_realpath,
                exe_version=exe_version,
                env_fingerprint=fingerprint,
                exit_code=result.exit_code,
                duration_s=result.duration_s,
                output_digest=output_digest(result),
                binding=binding,
            )
        )
    return records

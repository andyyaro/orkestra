"""Docker sandbox wrapping for external-command agents (ADR-0009).

A pure argv transformation applied at dispatch time: the agent's normal
``InvocationSpec`` is executed inside a hardened, network-less container
with only the task worktree mounted. Vendor CLIs are never containerized
in v0.2 (credential-exposure constraint — see the ADR).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from orkestra.adapters.base import InvocationSpec

if TYPE_CHECKING:
    from orkestra.schemas.config import ProjectConfig

CONTAINER_WORKDIR = "/work"

#: Adapters that may run sandboxed (their auth is user-managed, not a
#: host credential store the container would need).
SANDBOXABLE_ADAPTERS = frozenset({"external", "fake"})


def wrap_in_docker(
    spec: InvocationSpec,
    image: str,
    *,
    uid: int | None = None,
    gid: int | None = None,
    memory: str = "2g",
    cpus: str = "2",
    pids_limit: int = 256,
) -> InvocationSpec:
    """Return *spec* rewritten to run inside a hardened container.

    The original ``spec.cwd`` (the worktree) is mounted at ``/work``;
    everything else about the invocation — stdin brief, timeout,
    environment extras — is preserved.
    """
    uid = os.getuid() if uid is None else uid
    gid = os.getgid() if gid is None else gid
    argv = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--pids-limit",
        str(pids_limit),
        "--user",
        f"{uid}:{gid}",
        "-v",
        f"{spec.cwd}:{CONTAINER_WORKDIR}",
        "-w",
        CONTAINER_WORKDIR,
        "-e",
        "HOME=/tmp",
    ]
    for key, value in spec.env_extra.items():
        argv += ["-e", f"{key}={value}"]
    argv.append(image)
    argv += spec.argv
    stdin = spec.stdin_data
    if stdin is not None:
        # Protocol briefs carry the host worktree path; inside the
        # container the same directory is /work.
        stdin = stdin.replace(spec.cwd.encode(), CONTAINER_WORKDIR.encode())
    return InvocationSpec(
        argv=argv,
        cwd=spec.cwd,
        env_extra={},  # host docker client needs no agent env
        stdin_data=stdin,
        timeout_s=spec.timeout_s,
    )


def validate_sandbox_config(config: ProjectConfig) -> list[str]:
    """Config-time errors for `policy.sandbox = 'docker'` (empty = valid)."""
    errors: list[str] = []
    for name, agent in config.enabled_agents.items():
        if agent.adapter not in SANDBOXABLE_ADAPTERS:
            errors.append(
                f"agent {name!r} uses adapter {agent.adapter!r}: vendor CLIs "
                "cannot run in the docker sandbox (they authenticate through "
                "host credential stores Orkestra refuses to mount — ADR-0009). "
                'Disable the agent or use sandbox = "none".'
            )
        elif not agent.sandbox_image:
            errors.append(
                f'agent {name!r}: policy.sandbox = "docker" requires '
                'sandbox_image = "<image>" (the container the agent '
                "command runs in)"
            )
    return errors

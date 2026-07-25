"""Live docker-sandbox E2E: an external protocol agent runs in a real,
hardened container (skipped when no Docker daemon is available)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import orkestra.adapters.fake_worker as fake_worker_module
from orkestra.app import build_app
from orkestra.schemas.common import RunState, TaskKind
from orkestra.schemas.task import Assignment, TaskSpec
from orkestra.workspace.git import GitRepo

IMAGE = "python:3.12-slim"

pytestmark = [pytest.mark.e2e, pytest.mark.docker]


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
    return probe.returncode == 0


requires_docker = pytest.mark.skipif(not docker_ready(), reason="docker daemon unavailable")

CONFIG = f"""
version = 1

[project]
name = "docker-demo"

[agents.alpha]
adapter = "external"
command = ["python3", "agent.py"]
sandbox_image = "{IMAGE}"

[agents.beta]
adapter = "external"
command = ["python3", "agent.py"]
sandbox_image = "{IMAGE}"

[director]
agent = "alpha"

[policy]
sandbox = "docker"
max_concurrency = 1

[probes]
mode = "off"
"""


@requires_docker
async def test_external_agent_runs_sandboxed(tmp_path: Path) -> None:
    pull = subprocess.run(["docker", "pull", IMAGE], capture_output=True, timeout=300, check=False)
    if pull.returncode != 0:
        pytest.skip(f"cannot pull {IMAGE}: {pull.stderr.decode()[:200]}")

    root = tmp_path / "proj"
    root.mkdir()
    repo = GitRepo(root)
    await repo.init()
    # The agent is the stdlib-only fake worker, committed into the repo so
    # it exists inside every worktree at /work/agent.py.
    agent_source = Path(fake_worker_module.__file__).read_text()
    (root / "agent.py").write_text(agent_source)
    (root / ".gitignore").write_text(".orkestra/\n")
    (root / ".orkestra").mkdir()
    (root / ".orkestra" / "config.toml").write_text(CONFIG)
    await repo.add_all_and_commit("initial")

    app = build_app(root, offline=True)
    try:
        run_id = app.store.create_run("docker-demo")
        base, integration = await app.workspaces.start_run(run_id)
        app.store.set_run_git(run_id, base, integration)
        app.store.add_task(
            run_id,
            TaskSpec(
                key="boxed",
                title="write from inside the container",
                kind=TaskKind.IMPLEMENT,
                description="FAKE:write:sandboxed.txt:hello-from-container",
            ),
            Assignment(primary="alpha", reviewers=["beta"]),
        )
        state = await app.orchestrator.execute(run_id)
        assert state is RunState.COMPLETE
        _, out, _ = await repo._git("show", f"{integration}:sandboxed.txt")
        assert out.strip() == "hello-from-container"
        # The container had no network and ran as the host (non-root) user.
        events = app.store.events_for_run(run_id, limit=300)
        started = [e for e in events if "docker run --rm" in e["text"]]
        assert started, "agent was not dispatched through docker"
    finally:
        app.close()

"""E2E fixtures: real git repos + fake agents + the full kernel."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.app import App, build_app
from orkestra.workspace.git import GitRepo

CONFIG_TEMPLATE = """
version = 1

[project]
name = "e2e-demo"

{agents}

[director]
agent = "alpha"

[policy]
max_concurrency = {concurrency}
max_attempts_per_task = 3
max_review_cycles = 2

[probes]
mode = "off"
"""


def agent_block(name: str, adapter: str = "fake", command: list[str] | None = None) -> str:
    lines = [f"[agents.{name}]", f'adapter = "{adapter}"']
    if command:
        rendered = ", ".join(f'"{c}"' for c in command)
        lines.append(f"command = [{rendered}]")
    return "\n".join(lines)


async def make_project(
    tmp_path: Path,
    agent_names: list[str] | None = None,
    *,
    concurrency: int = 2,
    extra_agents: str = "",
) -> App:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    repo = GitRepo(root)
    await repo.init()
    (root / "README.md").write_text("# demo\n")
    agents = "\n\n".join(agent_block(name) for name in (agent_names or ["alpha", "beta"]))
    if extra_agents:
        agents += "\n\n" + extra_agents
    orkestra_dir = root / ".orkestra"
    orkestra_dir.mkdir(exist_ok=True)
    (orkestra_dir / "config.toml").write_text(
        CONFIG_TEMPLATE.format(agents=agents, concurrency=concurrency)
    )
    (root / ".gitignore").write_text(".orkestra/\n")
    await repo.add_all_and_commit("initial")
    return build_app(root, offline=True)


@pytest.fixture
async def app(tmp_path: Path) -> App:
    application = await make_project(tmp_path)
    yield application
    application.close()

"""Application wiring: config + store + adapters + policy + kernel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orkestra.adapters import build_adapter
from orkestra.adapters.base import AgentAdapter
from orkestra.director import DirectorService
from orkestra.errors import ConfigError
from orkestra.kernel.scheduler import Orchestrator
from orkestra.policy import PolicyEngine
from orkestra.schemas.config import ProjectConfig, load_config
from orkestra.store import Database, Store
from orkestra.workspace import WorkspaceManager

CONFIG_RELPATH = Path(".orkestra") / "config.toml"
DB_RELPATH = Path(".orkestra") / "orkestra.db"


@dataclass
class App:
    root: Path
    config: ProjectConfig
    store: Store
    adapters: dict[str, AgentAdapter]
    policy: PolicyEngine
    workspaces: WorkspaceManager
    orchestrator: Orchestrator
    director: DirectorService

    def close(self) -> None:
        self.store.db.close()


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the directory containing .orkestra/config.toml."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_RELPATH).is_file():
            return candidate
    msg = (
        f"no Orkestra project found from {current} upward — run `orkestra init` "
        "in your project directory first"
    )
    raise ConfigError(msg)


def build_app(root: Path | None = None, *, offline: bool = False) -> App:
    project_root = find_project_root(root)
    config = load_config(project_root / CONFIG_RELPATH)
    if config.policy.sandbox == "docker":
        msg = (
            "policy.sandbox = 'docker' is not yet supported in v0.1: vendor "
            "CLIs cannot authenticate inside containers without exposing host "
            "credentials, which Orkestra refuses to do. Agent-native OS "
            "sandboxes remain active. Track progress in ROADMAP.md (v0.2)."
        )
        raise ConfigError(msg)
    store = Store(Database(project_root / DB_RELPATH))
    adapters = {
        name: build_adapter(name, agent_config)
        for name, agent_config in config.enabled_agents.items()
    }
    policy = PolicyEngine(config.policy, list(config.enabled_agents.keys()))
    workspaces = WorkspaceManager(project_root, policy)
    orchestrator = Orchestrator(project_root, config, store, adapters, policy, workspaces)
    director = DirectorService(
        config.director.agent,
        adapters[config.director.agent],
        policy,
        project_root,
        max_retries=config.director.max_decision_retries,
        offline=offline,
    )
    orchestrator.director_service = director
    return App(
        root=project_root,
        config=config,
        store=store,
        adapters=adapters,
        policy=policy,
        workspaces=workspaces,
        orchestrator=orchestrator,
        director=director,
    )

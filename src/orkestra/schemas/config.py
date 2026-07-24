"""Project configuration schema (`.orkestra/config.toml`).

Versioned: ``version = 1``. Unknown top-level keys are rejected to catch
typos early; precise error messages are a product requirement.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from orkestra.errors import ConfigError

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]

CONFIG_VERSION = 1


class AgentConfig(BaseModel):
    """One enabled agent (an adapter binding plus profile options)."""

    model_config = ConfigDict(extra="forbid")

    adapter: Slug
    enabled: bool = True
    model: str | None = None
    autonomy: Literal["safe", "unsafe-full"] = "safe"
    timeout_s: int = Field(default=1800, ge=30, le=24 * 3600)
    # external-command adapters only:
    command: list[str] | None = None

    @model_validator(mode="after")
    def _external_needs_command(self) -> Self:
        if self.adapter == "external" and not self.command:
            msg = "agents using adapter='external' must set command = [...]"
            raise ValueError(msg)
        if self.adapter != "external" and self.command:
            msg = "command = [...] is only valid with adapter='external'"
            raise ValueError(msg)
        return self


class DirectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: Slug = "claude"
    max_decision_retries: int = Field(default=2, ge=0, le=5)


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrency: int = Field(default=2, ge=1, le=32)
    max_attempts_per_task: int = Field(default=3, ge=1, le=10)
    max_review_cycles: int = Field(default=2, ge=0, le=5)
    require_review: bool = True
    allow_push: bool = False
    task_timeout_s: int = Field(default=1800, ge=30, le=24 * 3600)
    protected_paths: list[str] = Field(
        default_factory=lambda: [".git", ".orkestra", ".github/workflows"]
    )
    sandbox: Literal["none", "docker"] = "none"


class VerifyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[str] = Field(default_factory=list)
    timeout_s: int = Field(default=900, ge=10, le=4 * 3600)


class ProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["live", "cached", "off"] = "cached"
    budget: int = Field(default=6, ge=0, le=50)
    timeout_s: int = Field(default=240, ge=10, le=3600)


class ProjectSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Slug
    spec_file: str = "SPEC.md"


class ProjectConfig(BaseModel):
    """Root configuration document."""

    model_config = ConfigDict(extra="forbid")

    version: int
    project: ProjectSection
    agents: dict[Slug, AgentConfig]
    director: DirectorConfig = Field(default_factory=DirectorConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    probes: ProbeConfig = Field(default_factory=ProbeConfig)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.version != CONFIG_VERSION:
            msg = f"config version {self.version} is not supported (expected {CONFIG_VERSION})"
            raise ValueError(msg)
        enabled = [name for name, a in self.agents.items() if a.enabled]
        if len(enabled) < 2:
            msg = (
                f"at least two enabled agents are required, found {len(enabled)} "
                f"({', '.join(enabled) or 'none'}) — Orkestra orchestrates *multiple* agents"
            )
            raise ValueError(msg)
        if self.director.agent not in self.agents:
            msg = (
                f"director.agent {self.director.agent!r} is not a configured agent "
                f"(configured: {', '.join(self.agents)})"
            )
            raise ValueError(msg)
        if not self.agents[self.director.agent].enabled:
            msg = f"director.agent {self.director.agent!r} is disabled"
            raise ValueError(msg)
        return self

    @property
    def enabled_agents(self) -> dict[str, AgentConfig]:
        return {name: a for name, a in self.agents.items() if a.enabled}


def load_config(path: Path) -> ProjectConfig:
    """Load and validate a config file with precise errors."""
    if not path.is_file():
        msg = f"config file not found: {path}"
        raise ConfigError(msg)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: invalid TOML: {exc}"
        raise ConfigError(msg) from exc
    try:
        return ProjectConfig.model_validate(raw)
    except Exception as exc:
        msg = f"{path}: invalid configuration:\n{exc}"
        raise ConfigError(msg) from exc

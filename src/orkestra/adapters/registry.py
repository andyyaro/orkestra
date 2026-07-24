"""Adapter construction from configuration (no dynamic code loading)."""

from __future__ import annotations

from orkestra.adapters.antigravity_cli import AntigravityCliAdapter
from orkestra.adapters.base import AgentAdapter
from orkestra.adapters.claude_code import ClaudeCodeAdapter
from orkestra.adapters.codex_cli import CodexCliAdapter
from orkestra.adapters.external import ExternalAdapter
from orkestra.adapters.fake import FakeAdapter
from orkestra.adapters.gemini_cli import GeminiCliAdapter
from orkestra.errors import ConfigError
from orkestra.schemas.config import AgentConfig


def builtin_adapter_ids() -> list[str]:
    return ["claude-code", "codex-cli", "antigravity-cli", "gemini-cli", "fake", "external"]


def build_adapter(agent_name: str, config: AgentConfig) -> AgentAdapter:
    """Instantiate the adapter bound to one configured agent."""
    adapter_id = config.adapter
    if adapter_id == "claude-code":
        return ClaudeCodeAdapter(model=config.model, autonomy=config.autonomy)
    if adapter_id == "codex-cli":
        return CodexCliAdapter(model=config.model, autonomy=config.autonomy)
    if adapter_id == "antigravity-cli":
        return AntigravityCliAdapter(model=config.model, autonomy=config.autonomy)
    if adapter_id == "gemini-cli":
        return GeminiCliAdapter(model=config.model, autonomy=config.autonomy)
    if adapter_id == "fake":
        return FakeAdapter(model=config.model, autonomy=config.autonomy)
    if adapter_id == "external":
        assert config.command is not None  # validated by AgentConfig
        return ExternalAdapter(command=config.command, name=agent_name)
    msg = (
        f"agent {agent_name!r}: unknown adapter {adapter_id!r} "
        f"(built-in adapters: {', '.join(builtin_adapter_ids())})"
    )
    raise ConfigError(msg)

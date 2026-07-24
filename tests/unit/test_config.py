"""Unit tests: configuration schema and loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.errors import ConfigError
from orkestra.schemas.config import ProjectConfig, load_config

VALID = """
version = 1

[project]
name = "demo"

[agents.claude]
adapter = "claude-code"

[agents.codex]
adapter = "codex-cli"

[agents.anti]
adapter = "antigravity-cli"

[agents.extra]
adapter = "fake"
enabled = false
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


class TestValid:
    def test_loads(self, tmp_path: Path) -> None:
        cfg = load_config(write(tmp_path, VALID))
        assert cfg.project.name == "demo"
        assert set(cfg.enabled_agents) == {"claude", "codex", "anti"}
        assert cfg.director.agent == "claude"
        assert cfg.policy.max_concurrency == 2  # safe default

    def test_two_agents_is_enough(self, tmp_path: Path) -> None:
        text = VALID.replace('[agents.anti]\nadapter = "antigravity-cli"\n\n', "")
        cfg = load_config(write(tmp_path, text))
        assert len(cfg.enabled_agents) == 2

    def test_many_agents_supported(self, tmp_path: Path) -> None:
        extra = "".join(
            f'\n[agents.fake{i}]\nadapter = "fake"\n' for i in range(6)
        )
        cfg = load_config(write(tmp_path, VALID + extra))
        assert len(cfg.enabled_agents) == 9  # no fixed-three assumption anywhere


class TestInvalid:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nope.toml")

    def test_bad_toml(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="invalid TOML"):
            load_config(write(tmp_path, "version = ["))

    def test_wrong_version(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="version 99 is not supported"):
            load_config(write(tmp_path, VALID.replace("version = 1", "version = 99")))

    def test_fewer_than_two_agents_rejected(self, tmp_path: Path) -> None:
        text = """
version = 1
[project]
name = "demo"
[agents.solo]
adapter = "claude-code"
"""
        with pytest.raises(ConfigError, match="at least two enabled agents"):
            load_config(write(tmp_path, text))

    def test_unknown_director_rejected(self, tmp_path: Path) -> None:
        text = VALID + '\n[director]\nagent = "ghost"\n'
        with pytest.raises(ConfigError, match="not a configured agent"):
            load_config(write(tmp_path, text))

    def test_disabled_director_rejected(self, tmp_path: Path) -> None:
        text = VALID + '\n[director]\nagent = "extra"\n'
        with pytest.raises(ConfigError, match="disabled"):
            load_config(write(tmp_path, text))

    def test_typo_key_rejected(self, tmp_path: Path) -> None:
        text = VALID + "\n[policy]\nmax_concurency = 3\n"
        with pytest.raises(ConfigError):
            load_config(write(tmp_path, text))

    def test_external_adapter_requires_command(self, tmp_path: Path) -> None:
        text = VALID + '\n[agents.thirdparty]\nadapter = "external"\n'
        with pytest.raises(ConfigError, match="command"):
            load_config(write(tmp_path, text))

    def test_director_default_is_claude(self) -> None:
        # Schema-level check that the documented default holds.
        raw = {
            "version": 1,
            "project": {"name": "x"},
            "agents": {
                "claude": {"adapter": "claude-code"},
                "codex": {"adapter": "codex-cli"},
            },
        }
        cfg = ProjectConfig.model_validate(raw)
        assert cfg.director.agent == "claude"

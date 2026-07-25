"""Unit tests: v0.2-era config migration, duplicate profiles, model
discovery cache, stale models, provenance."""

from __future__ import annotations

from pathlib import Path

from orkestra.adapters import build_adapter
from orkestra.adapters.models import (
    ModelCatalog,
    _read_cache,
    _write_cache,
    discover_models,
    model_provenance,
)
from orkestra.schemas.config import load_config

# A verbatim config from the v0.2.0 era (pre effort/presets/start).
V02_CONFIG = """
version = 1

[project]
name = "legacy"
spec_file = "SPEC.md"

[agents.claude]
adapter = "claude-code"
model = "sonnet"

[agents.codex]
adapter = "codex-cli"
token_budget = 50000

[agents.antigravity]
adapter = "antigravity-cli"
enabled = false

[director]
agent = "claude"

[policy]
max_concurrency = 2
max_attempts_per_task = 3

[verify]
commands = ["pytest -q"]

[probes]
mode = "cached"
budget = 6
"""


class TestV02Migration:
    def test_legacy_config_loads_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(V02_CONFIG)
        config = load_config(path)
        assert config.agents["claude"].model == "sonnet"
        assert config.agents["claude"].effort is None  # new field defaults
        assert config.agents["codex"].token_budget == 50000

    def test_safe_defaults_did_not_move(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(V02_CONFIG)
        config = load_config(path)
        assert config.policy.require_review is True
        assert config.policy.allow_push is False
        assert config.policy.sandbox == "none"
        assert config.policy.session_reuse is True
        assert config.policy.max_review_cycles == 2
        assert ".github/workflows" in config.policy.protected_paths


class TestDuplicateProfiles:
    def test_two_profiles_of_one_adapter(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(
            V02_CONFIG.replace(
                '[agents.claude]\nadapter = "claude-code"\nmodel = "sonnet"',
                '[agents.claude-deep]\nadapter = "claude-code"\nmodel = "opus"\n\n'
                '[agents.claude-fast]\nadapter = "claude-code"\nmodel = "haiku"',
            ).replace('agent = "claude"', 'agent = "claude-deep"')
        )
        config = load_config(path)
        deep = build_adapter("claude-deep", config.agents["claude-deep"])
        fast = build_adapter("claude-fast", config.agents["claude-fast"])
        assert deep.model == "opus" and fast.model == "haiku"  # type: ignore[attr-defined]
        assert deep is not fast


class TestDiscoveryCache:
    def test_cache_roundtrip(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, {"a:1": {"models": ["m1"], "ts": 123.0}})
        assert _read_cache(tmp_path)["a:1"]["models"] == ["m1"]

    def test_corrupt_cache_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / ".orkestra" / "cache" / "models.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        assert _read_cache(tmp_path) == {}

    async def test_documented_catalogs(self, tmp_path: Path) -> None:
        from orkestra.schemas.config import AgentConfig

        claude = build_adapter("c", AgentConfig(adapter="claude-code"))
        catalog = await discover_models(claude, tmp_path)
        assert "sonnet" in catalog.models
        assert catalog.provenance == "documented"

    async def test_unknown_adapter_manual_fallback(self, tmp_path: Path) -> None:
        from orkestra.schemas.config import AgentConfig

        external = build_adapter("x", AgentConfig(adapter="external", command=["/bin/echo"]))
        catalog = await discover_models(external, tmp_path)
        assert catalog.models == []
        assert catalog.provenance == "none"


class TestProvenance:
    CATALOG = ModelCatalog(
        adapter_id="claude-code", models=["sonnet", "opus"], provenance="documented"
    )

    def test_default(self) -> None:
        assert model_provenance(None, self.CATALOG) == "default"

    def test_known(self) -> None:
        assert model_provenance("sonnet", self.CATALOG) == "documented"

    def test_stale_or_custom_is_manual(self) -> None:
        # A model that no longer exists in the catalog is shown as manual —
        # visible, not hidden, so users notice stale values.
        assert model_provenance("claude-2024-legacy", self.CATALOG) == "manual"


class TestStaleModelValues:
    def test_stale_model_does_not_break_run_config(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(V02_CONFIG.replace('model = "sonnet"', 'model = "some-retired-model-name"'))
        config = load_config(path)  # config layer accepts; runtime surfaces errors
        assert config.agents["claude"].model == "some-retired-model-name"

"""Unit tests: provider-neutral effort — validation, mapping, exact argv."""

from __future__ import annotations

import pytest

from orkestra.schemas.common import TaskKind
from orkestra.schemas.config import ProjectConfig
from orkestra.schemas.effort import ADAPTER_EFFORT, EFFORT_LEVELS, validate_effort
from orkestra.schemas.task import TaskBrief


def brief() -> TaskBrief:
    return TaskBrief(task_id="t", run_id="r", title="x", kind=TaskKind.IMPLEMENT,
                     instructions="do", cwd="/tmp", timeout_s=60)


def config_with(adapter: str, effort: str) -> dict:  # type: ignore[type-arg]
    return {
        "version": 1,
        "project": {"name": "e"},
        "agents": {
            "one": {"adapter": adapter, "effort": effort,
                    **({"command": ["/x"]} if adapter == "external" else {})},
            "two": {"adapter": "fake"},
        },
        "director": {"agent": "two"},
    }


class TestValidation:
    @pytest.mark.parametrize("adapter", list(ADAPTER_EFFORT))
    def test_auto_accepted_everywhere(self, adapter: str) -> None:
        assert validate_effort(adapter, "auto") is None
        assert validate_effort(adapter, None) is None

    def test_claude_rejects_all_tiers_with_plain_language(self) -> None:
        for level in ("low", "medium", "high", "max"):
            error = validate_effort("claude-code", level)
            assert error is not None
            assert "no effort control" in error
            assert "model tier" in error  # tells the user what to do instead

    def test_gemini_rejects_with_alternative(self) -> None:
        error = validate_effort("gemini-cli", "high")
        assert error is not None and "flash" in error

    def test_max_rejected_where_top_is_high(self) -> None:
        for adapter in ("antigravity-cli", "codex-cli"):
            error = validate_effort(adapter, "max")
            assert error is not None and "high" in error and "max" in error

    def test_supported_levels_pass(self) -> None:
        for adapter in ("antigravity-cli", "codex-cli"):
            for level in ("low", "medium", "high"):
                assert validate_effort(adapter, level) is None

    def test_config_rejects_unsupported_never_silent(self) -> None:
        with pytest.raises(Exception, match="no effort control"):
            ProjectConfig.model_validate(config_with("claude-code", "high"))

    def test_config_accepts_supported(self) -> None:
        config = ProjectConfig.model_validate(config_with("antigravity-cli", "high"))
        assert config.agents["one"].effort == "high"

    def test_levels_vocabulary(self) -> None:
        assert EFFORT_LEVELS == ("auto", "low", "medium", "high", "max")


class TestExactCommandConstruction:
    """Every supported (adapter, level) pair produces exactly the right argv."""

    @pytest.mark.parametrize("level,cli", [("low", "low"), ("medium", "medium"),
                                           ("high", "high")])
    def test_antigravity(self, level: str, cli: str) -> None:
        from orkestra.adapters.antigravity_cli import AntigravityCliAdapter

        argv = AntigravityCliAdapter(effort=level).build_invocation(brief()).argv
        assert argv[argv.index("--effort") + 1] == cli

    @pytest.mark.parametrize("level,cli", [("low", "low"), ("medium", "medium"),
                                           ("high", "high")])
    def test_codex(self, level: str, cli: str) -> None:
        from orkestra.adapters.codex_cli import CodexCliAdapter

        argv = CodexCliAdapter(effort=level).build_invocation(brief()).argv
        assert f'model_reasoning_effort="{cli}"' in argv

    @pytest.mark.parametrize("adapter_module,cls", [
        ("orkestra.adapters.antigravity_cli", "AntigravityCliAdapter"),
        ("orkestra.adapters.codex_cli", "CodexCliAdapter"),
    ])
    def test_auto_emits_nothing(self, adapter_module: str, cls: str) -> None:
        import importlib

        adapter = getattr(importlib.import_module(adapter_module), cls)(effort="auto")
        argv = adapter.build_invocation(brief()).argv
        assert "--effort" not in argv
        assert not any("model_reasoning_effort" in a for a in argv)

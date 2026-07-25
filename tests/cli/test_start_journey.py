"""Terminal-level E2E of the coherent journey: start → run → diff → merge.

Agent detection is monkeypatched so the tests are deterministic on any
machine (a dev box with real CLIs signed in must behave like CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import orkestra.cli.start as start_module
from orkestra.cli.main import app
from orkestra.schemas.config import load_config

runner = CliRunner()


def mock_detection(monkeypatch: pytest.MonkeyPatch, ready: dict[str, bool]) -> None:
    async def fake_detect() -> dict[str, dict[str, str]]:
        return {
            adapter_id: {
                "version": "9.9.9",
                "ready": "yes" if is_ready else "no",
                "detail": "mocked",
            }
            for adapter_id, is_ready in ready.items()
        }

    monkeypatch.setattr(start_module, "_detect_ready_adapters", fake_detect)


class TestPracticeModeJourney:
    """First-time user, nothing signed in: the whole journey still works."""

    def test_start_run_diff_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_detection(monkeypatch, {})  # no agents anywhere
        root = tmp_path / "first-project"
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["start", str(root), "--non-interactive", "--run"])
        assert result.exit_code == 0, result.output
        assert "practice mode" in result.output
        assert "run complete" in result.output
        # Journey continues with the same friendly commands.
        monkeypatch.chdir(root)
        result = runner.invoke(app, ["review"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(app, ["accept", "--cleanup", "--yes"])
        assert result.exit_code == 0, result.output
        assert "accepted" in result.output

    def test_no_toml_knowledge_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "p"
        result = runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run"])
        assert result.exit_code == 0, result.output
        # The user never opened the file, but it is valid and complete.
        config = load_config(root / ".orkestra" / "config.toml")
        assert len(config.enabled_agents) == 2
        assert config.policy.require_review is True  # safety not preset-tunable


class TestPresets:
    def test_max_quality_creates_dual_claude_profiles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(
            monkeypatch,
            {"claude-code": True, "codex-cli": True, "antigravity-cli": True},
        )
        root = tmp_path / "maxq"
        result = runner.invoke(
            app,
            ["start", str(root), "--non-interactive", "--preset", "max-quality", "--no-run"],
        )
        assert result.exit_code == 0, result.output
        config = load_config(root / ".orkestra" / "config.toml")
        agents = config.enabled_agents
        assert set(agents) == {"claude-deep", "claude-fast", "codex", "antigravity"}
        assert agents["claude-deep"].model == "opus"
        assert agents["claude-fast"].model == "haiku"
        assert agents["codex"].effort == "high"
        assert agents["antigravity"].effort == "high"
        assert config.director.agent == "claude-deep"
        assert config.probes.mode == "live"
        # Presets must never weaken safety.
        assert config.policy.require_review is True
        assert config.policy.allow_push is False

    def test_faster_preset(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_detection(monkeypatch, {"claude-code": True, "codex-cli": True})
        root = tmp_path / "fast"
        result = runner.invoke(
            app,
            ["start", str(root), "--non-interactive", "--preset", "faster", "--no-run"],
        )
        assert result.exit_code == 0, result.output
        config = load_config(root / ".orkestra" / "config.toml")
        assert config.agents["claude"].model == "haiku"
        assert config.agents["codex"].effort == "low"
        assert config.probes.mode == "off"

    def test_unknown_preset_fails_helpfully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        result = runner.invoke(
            app,
            ["start", str(tmp_path / "x"), "--non-interactive", "--preset", "turbo", "--no-run"],
        )
        assert result.exit_code == 1
        assert "balanced" in result.output  # lists valid options


class TestInteractiveStart:
    def test_preset_menu_and_spec_questions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "wiz"
        # inputs: preset "1" (Faster) · verify skip (blank) · spec goal ·
        # constraints (default) · success (default) · run now? n
        result = runner.invoke(
            app,
            ["start", str(root)],
            input="1\n\nbuild a tiny CLI that greets people\n\n\nn\n",
        )
        assert result.exit_code == 0, result.output
        assert "How should the agents be tuned?" in result.output
        spec = (root / "SPEC.md").read_text()
        assert "greets people" in spec
        assert "Acceptance" in spec
        config = load_config(root / ".orkestra" / "config.toml")
        assert config.probes.mode == "off"  # Faster preset applied

    def test_reconfigure_existing_project_preserves_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "again"
        runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run"])
        (root / "SPEC.md").write_text(
            "# Mine\n\nA real spec I wrote (must pass tests).\nDo not touch docs.\n" * 4
        )
        # Uncommitted edits now (correctly) block start; commit like the
        # guidance says, then reconfigure.
        import subprocess

        subprocess.run(["git", "add", "SPEC.md"], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid",
             "commit", "-q", "-m", "my spec"],
            cwd=root, check=True, capture_output=True,
        )
        result = runner.invoke(
            app,
            ["start", str(root), "--non-interactive", "--preset", "balanced", "--no-run"],
        )
        assert result.exit_code == 0, result.output
        assert "A real spec I wrote" in (root / "SPEC.md").read_text()


class TestModelsScreen:
    def test_models_shows_profiles_and_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_detection(monkeypatch, {})
        root = tmp_path / "screen"
        runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run"])
        monkeypatch.chdir(root)
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 0, result.output
        assert "ada" in result.output and "grace" in result.output
        assert "default" in result.output  # provenance column

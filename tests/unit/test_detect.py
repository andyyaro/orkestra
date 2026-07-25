"""Unit tests: project detection heuristics and spec nudges."""

from __future__ import annotations

import json
from pathlib import Path

from orkestra.cli.detect import detect_verify_commands, spec_nudges


class TestDetectVerify:
    def test_python_pytest_with_uv(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        (tmp_path / "uv.lock").write_text("")
        assert detect_verify_commands(tmp_path) == ["uv run pytest -q"]

    def test_unittest_project_gets_unittest_command(self, tmp_path: Path) -> None:
        # Recommending pytest here would produce a gate that cannot run.
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n"
            "    def test_a(self):\n        pass\n"
        )
        assert detect_verify_commands(tmp_path) == ["python3 -m unittest discover -q"]

    def test_pytest_imports_detected(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_y.py").write_text(
            "import pytest\n\n\ndef test_b():\n    pass\n"
        )
        (tmp_path / "uv.lock").write_text("")
        assert detect_verify_commands(tmp_path) == ["uv run pytest -q"]

    def test_empty_tests_dir_suggests_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        assert detect_verify_commands(tmp_path) == []

    def test_node_with_real_test_script(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}))
        assert detect_verify_commands(tmp_path) == ["npm test --silent"]

    def test_node_placeholder_script_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})
        )
        assert detect_verify_commands(tmp_path) == []

    def test_rust_and_go(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        (tmp_path / "go.mod").write_text("module x\n")
        assert detect_verify_commands(tmp_path) == ["cargo test", "go test ./..."]

    def test_empty_project(self, tmp_path: Path) -> None:
        assert detect_verify_commands(tmp_path) == []

    def test_malformed_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{broken")
        assert detect_verify_commands(tmp_path) == []


class TestSpecNudges:
    GOOD = (
        "# Rate limiter\n\n## Goals\n\nAdd a token-bucket rate limiter to "
        "src/middleware.py with per-key buckets and a shared clock abstraction "
        "so tests can control time precisely without sleeping.\n\n"
        "## Constraints\n\nDo not touch the auth module or add dependencies.\n\n"
        "## Acceptance\n\n`pytest -q` must pass; bursts above the limit must "
        "return 429 exactly.\n"
    )

    def test_good_spec_no_nudges(self) -> None:
        assert spec_nudges(self.GOOD) == []

    def test_short_spec(self) -> None:
        assert any("very short" in n for n in spec_nudges("# x\nbuild the thing"))

    def test_template_placeholders(self) -> None:
        text = self.GOOD + "\n- ...\n"
        assert any("template placeholders" in n for n in spec_nudges(text))

    def test_no_headings(self) -> None:
        text = "Build a thing that does stuff for users and must pass tests. " * 8
        nudges = spec_nudges(text + " do not touch ci.")
        assert any("no headings" in n for n in nudges)

    def test_no_acceptance_language(self) -> None:
        text = (
            "# T\n\n## Goals\n\n"
            + ("make it nice and fast for people. " * 10)
            + "\nDo not touch docs.\n"
        )
        assert any("acceptance" in n for n in spec_nudges(text))

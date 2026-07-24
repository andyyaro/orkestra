"""Unit tests: app wiring guards."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orkestra.app import build_app, find_project_root
from orkestra.errors import ConfigError

CONFIG = """
version = 1
[project]
name = "x"
[agents.a]
adapter = "fake"
[agents.b]
adapter = "fake"
[director]
agent = "a"
{extra}
"""


def make(root: Path, extra: str = "") -> None:
    (root / ".orkestra").mkdir(parents=True)
    (root / ".orkestra" / "config.toml").write_text(CONFIG.format(extra=extra))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


class TestBuildApp:
    def test_docker_sandbox_rejected_in_v01(self, tmp_path: Path) -> None:
        make(tmp_path, '[policy]\nsandbox = "docker"\n')
        with pytest.raises(ConfigError, match="not yet supported in v0.1"):
            build_app(tmp_path)

    def test_find_project_root_walks_up(self, tmp_path: Path) -> None:
        make(tmp_path)
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        assert find_project_root(nested) == tmp_path

    def test_find_project_root_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="no Orkestra project"):
            find_project_root(tmp_path)

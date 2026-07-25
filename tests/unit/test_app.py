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
    def test_docker_sandbox_requires_images(self, tmp_path: Path) -> None:
        make(tmp_path, '[policy]\nsandbox = "docker"\n')
        with pytest.raises(ConfigError, match="sandbox_image"):
            build_app(tmp_path)

    def test_docker_sandbox_rejects_vendor_clis(self, tmp_path: Path) -> None:
        root = tmp_path / "vendor"
        root.mkdir()
        (root / ".orkestra").mkdir()
        (root / ".orkestra" / "config.toml").write_text(
            'version = 1\n[project]\nname = "x"\n'
            '[agents.claude]\nadapter = "claude-code"\n'
            '[agents.b]\nadapter = "fake"\nsandbox_image = "python:3.12-slim"\n'
            '[director]\nagent = "claude"\n'
            '[policy]\nsandbox = "docker"\n'
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        with pytest.raises(ConfigError, match="vendor CLIs cannot run"):
            build_app(root)

    def test_docker_sandbox_valid_with_images(self, tmp_path: Path) -> None:
        make(
            tmp_path,
            '[policy]\nsandbox = "docker"\n',
        )
        config = tmp_path / ".orkestra" / "config.toml"
        config.write_text(
            config.read_text().replace(
                'adapter = "fake"', 'adapter = "fake"\nsandbox_image = "python:3.12-slim"'
            )
        )
        app = build_app(tmp_path)
        app.close()

    def test_find_project_root_walks_up(self, tmp_path: Path) -> None:
        make(tmp_path)
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        assert find_project_root(nested) == tmp_path

    def test_find_project_root_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="no Orkestra project"):
            find_project_root(tmp_path)

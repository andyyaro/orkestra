"""The reported version must be the released version.

v0.5.4 shipped reporting `orkestra 0.5.3`, because the version lived in two
places and only one was bumped. The metadata said 0.5.4, the CLI said 0.5.3,
and every check passed. This pins both halves: the value is derived rather
than restated, and it still agrees with pyproject.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import orkestra

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def declared_version() -> str:
    return str(tomllib.loads(PYPROJECT.read_text())["project"]["version"])


class TestVersion:
    def test_matches_pyproject(self) -> None:
        # The installed distribution's metadata against the source of truth.
        # These can only disagree if someone bumped one and not the other,
        # which is exactly what happened for v0.5.4.
        assert orkestra.__version__ == declared_version()

    def test_is_derived_rather_than_restated(self) -> None:
        source = Path(orkestra.__file__).read_text()
        assert 'version("orkestra-runtime")' in source, (
            "the version is no longer derived from package metadata; a second "
            "copy can drift from pyproject, which is how v0.5.4 shipped "
            "reporting 0.5.3"
        )
        # The only literal allowed here is the not-installed fallback.
        literals = re.findall(r'__version__ = "([^"]+)"', source)
        assert literals in ([], ["0.0.0+unknown"]), literals

    def test_the_cli_reports_it(self) -> None:
        from typer.testing import CliRunner

        from tests.cli.asserts import invoke

        result = invoke(CliRunner(), ["--version"], 0)
        assert declared_version() in result.output

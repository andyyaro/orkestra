"""The optional-memory suite must not be able to certify itself by skipping.

`tests/test_memory.py` is the only module that drives the Provalume bridge
against a real database. It was guarded by `pytest.importorskip`, and the gate
that certifies this branch installs no extras — so every one of those assertions
was skipped while the run reported green, and the feature the branch exists to
add went entirely unverified.

The skip is still correct for a user who does not want the extra. What changed
is that a run which *means* to certify memory can say so and get a failure
instead of silence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REQUIRE_MEMORY_EXTRA_ENV, missing_memory_extra_is_fatal

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A module that fails to import, shadowing the installed package. Shadowing is
#: how the "extra not installed" configuration is reproduced without uninstalling
#: anything from the environment the rest of the suite is using.
BLOCKER = "raise ModuleNotFoundError(\"No module named 'provalume'\")\n"


def _pytest_executable() -> str:
    found = shutil.which("pytest") or str(Path(sys.executable).parent / "pytest")
    if not Path(found).exists():  # pragma: no cover - depends on the environment
        pytest.skip("no pytest executable to drive a subprocess collection with")
    return found


def _collect_without_provalume(
    tmp_path: Path, *, require: bool
) -> subprocess.CompletedProcess[str]:
    """Collect the memory suite with Provalume made unimportable."""
    (tmp_path / "provalume.py").write_text(BLOCKER)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), *(p for p in [env.get("PYTHONPATH")] if p)])
    if require:
        env[REQUIRE_MEMORY_EXTRA_ENV] = "1"
    else:
        env.pop(REQUIRE_MEMORY_EXTRA_ENV, None)
    return subprocess.run(
        [
            _pytest_executable(),
            "tests/test_memory.py",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize(
    ("value", "fatal"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("off", False),
    ],
)
def test_the_requirement_switch_reads_its_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, fatal: bool
) -> None:
    monkeypatch.setenv(REQUIRE_MEMORY_EXTRA_ENV, value)
    assert missing_memory_extra_is_fatal() is fatal


def test_the_switch_is_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent means "skip", so an ordinary contributor without the extra is
    unaffected."""
    monkeypatch.delenv(REQUIRE_MEMORY_EXTRA_ENV, raising=False)
    assert missing_memory_extra_is_fatal() is False


def test_a_missing_extra_fails_the_run_when_it_is_required(tmp_path: Path) -> None:
    """The outcome the finding is about: no more green-by-skipping."""
    result = _collect_without_provalume(tmp_path, require=True)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"a missing Provalume extra still passed:\n{combined}"
    assert REQUIRE_MEMORY_EXTRA_ENV in combined, combined
    assert "uv sync --extra memory" in combined, (
        f"the failure does not say how to fix it:\n{combined}"
    )


def test_a_missing_extra_still_skips_by_default(tmp_path: Path) -> None:
    """The other half: memory stays a genuinely optional extra."""
    result = _collect_without_provalume(tmp_path, require=False)
    combined = result.stdout + result.stderr
    assert REQUIRE_MEMORY_EXTRA_ENV not in combined, (
        f"an unset switch behaved as if it were set:\n{combined}"
    )
    assert "error" not in combined.lower(), combined

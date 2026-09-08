"""The README's test count must be the number pytest actually collects.

It said 472 for three releases. That was the collected count when it was
written and drifted to 548 without anything noticing, which is the failure
mode this project cares about most: a number nobody recounts. Confusingly,
472 is also today's count of test *functions*, so the claim reads plausible
while describing a metric the README does not name.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def collected_count() -> int:
    """What `pytest` reports, which is what a reader would check."""
    result = subprocess.run(  # nosec B603 - fixed argv, no shell, repo-local
        # No -q: pyproject already sets addopts="-q", and a second one is
        # double-quiet, which removes the very summary line we parse.
        [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        pytest.skip(f"could not read a collected count from pytest: {result.stdout[-300:]}")
    return int(match.group(1))


def test_readme_test_count_is_current() -> None:
    claimed = re.search(r"\*\*Verified\*\* - (\d+) tests", README.read_text())
    assert claimed, "README no longer states a test count in the expected shape"
    actual = collected_count()
    print(f"README claims {claimed.group(1)}; pytest collects {actual}")
    assert int(claimed.group(1)) == actual, (
        f"README says {claimed.group(1)} tests, pytest collects {actual}. Recount, then claim."
    )

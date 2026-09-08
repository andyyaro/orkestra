"""One place where CLI exit codes are asserted, and explained when they differ.

A bare ``assert result.exit_code == 0`` fails with ``assert 2 == 0`` and throws
away everything that would explain it: the command's own output, the argv that
produced it, and the traceback of any exception the Typer runner swallowed.

Two py3.12/macOS-only CI flakes were left undiagnosable exactly that way (runs
30184426039 and 32305921680). The second was an ``orkestra run --offline`` that
ended *waiting on a human decision* rather than completing, and the assertion
reported only ``assert 2 == 0`` - the one number that does not say so.
"""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from typing import Any

from typer.testing import CliRunner, Result

from orkestra.cli.main import app

# What the CLI's exit codes mean; see `run`/`resume` in src/orkestra/cli/main.py.
EXIT_MEANINGS: dict[int, str] = {
    0: "success",
    1: "failed",
    2: "waiting on a human decision",
    3: "cancelled",
}


def _describe_code(code: int | None) -> str:
    meaning = EXIT_MEANINGS.get(code) if code is not None else None
    return f"{code} ({meaning})" if meaning else str(code)


def explain(result: Result, expected: int, argv: Sequence[str] | None = None) -> str:
    """Render everything known about a CLI result, for an assertion message."""
    lines = [f"expected exit {_describe_code(expected)}, got {_describe_code(result.exit_code)}"]
    if argv is not None:
        lines.append(f"argv: {list(argv)}")
    lines.append("--- output ---")
    lines.append(result.output.strip() or "(no output)")
    exception = result.exception
    if exception is not None and not isinstance(exception, SystemExit):
        lines.append("--- exception ---")
        formatted = traceback.format_exception(type(exception), exception, exception.__traceback__)
        lines.append("".join(formatted).strip())
    return "\n".join(lines)


def assert_exit(result: Result, expected: int, *, argv: Sequence[str] | None = None) -> Result:
    """Assert a CLI exit code, reporting the whole result when it does not match."""
    if result.exit_code != expected:
        raise AssertionError(explain(result, expected, argv))
    return result


def invoke(runner: CliRunner, argv: Sequence[str], expected: int, **kwargs: Any) -> Result:
    """Invoke the CLI and assert its exit code in one step."""
    result = runner.invoke(app, list(argv), **kwargs)
    return assert_exit(result, expected, argv=argv)

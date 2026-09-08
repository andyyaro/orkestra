"""An agent must see the same tree its gate will judge.

Gates run with a worktree-scoped PYTHONPATH; agents did not. An agent
running the project's tests inside its own worktree therefore got exactly
the unbound behaviour the gate is protected from: it could see green where
the gate sees red, and could not reproduce its own rejection, which is the
one thing a repair brief asks it to do.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from orkestra.adapters.base import InvocationSpec, StreamParser
from orkestra.adapters.runner import run_invocation
from orkestra.schemas.agent import AgentEvent, AgentResult, ResultStatus
from orkestra.verify.runner import gate_env, subprocess_env


class _Collect(StreamParser):
    """Keeps every line, so the child's own report is the evidence."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def feed_line(self, line: str, *, is_stderr: bool) -> Iterable[AgentEvent]:
        self.lines.append(line)
        return ()

    def result(self, exit_code: int | None, duration_s: float, cwd: str) -> AgentResult:
        return AgentResult(
            status=ResultStatus.OK if exit_code == 0 else ResultStatus.ERROR,
            summary="\n".join(self.lines),
        )


class TestAgentsRunBoundToTheirWorktree:
    def test_the_gate_environment_differs_from_the_bare_one(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        bound = gate_env(tmp_path)
        assert bound["PYTHONPATH"].split(os.pathsep)[0] == str((tmp_path / "src").resolve())
        # What agents used to receive says nothing about the worktree at all.
        assert subprocess_env().get("PYTHONPATH", "") != bound["PYTHONPATH"]

    async def test_a_launched_agent_really_receives_it(self, tmp_path: Path) -> None:
        """Observed from inside the child, not asserted about the caller."""
        worktree = tmp_path / "wt"
        (worktree / "src").mkdir(parents=True)
        parser = _Collect()

        result = await run_invocation(
            InvocationSpec(
                argv=[sys.executable, "-c", "import os; print(os.environ.get('PYTHONPATH',''))"],
                cwd=str(worktree),
            ),
            parser=parser,
            on_event=lambda _event: None,
        )
        printed = "\n".join(parser.lines)
        print(f"child reported PYTHONPATH: {printed!r}")
        assert result.status is ResultStatus.OK, printed
        assert str((worktree / "src").resolve()) in printed

    async def test_the_agent_imports_its_own_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The behaviour, not the variable: same-named module, two trees.

        The inherited environment points at another checkout, which is the
        shape a src-layout editable install creates through its .pth file.
        The worktree must still win.
        """
        worktree = tmp_path / "wt"
        (worktree / "src").mkdir(parents=True)
        (worktree / "src" / "widget.py").write_text("ORIGIN = 'worktree'\n")
        other = tmp_path / "other"
        (other / "src").mkdir(parents=True)
        (other / "src" / "widget.py").write_text("ORIGIN = 'elsewhere'\n")
        monkeypatch.setenv("PYTHONPATH", str((other / "src").resolve()))

        parser = _Collect()
        result = await run_invocation(
            InvocationSpec(
                argv=[sys.executable, "-c", "import widget; print(widget.ORIGIN)"],
                cwd=str(worktree),
            ),
            parser=parser,
            on_event=lambda _event: None,
        )
        printed = "\n".join(parser.lines)
        print(f"agent imported widget from: {printed!r}")
        assert result.status is ResultStatus.OK, printed
        assert "worktree" in printed, (
            "the agent imported another checkout, which is the defect this closes"
        )

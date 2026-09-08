"""A diagnosis must survive the console's own truncation.

Three CI failures reached a human with the cause already removed: the event
renderer clips text at a fixed width, and a git worktree command's argv is
long enough to consume that entire budget before git's own error begins.
These tests pin the two halves of the fix - clip marks what it dropped, and
the git failure message leads with the reason rather than the argv.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.cli.text import clip
from orkestra.errors import WorkspaceError
from orkestra.workspace import GitRepo


class TestClip:
    def test_short_text_is_untouched(self) -> None:
        assert clip("hello", 220) == "hello"

    def test_exact_length_is_untouched(self) -> None:
        assert clip("abcde", 5) == "abcde"

    def test_overlong_text_is_marked(self) -> None:
        clipped = clip("a" * 300, 220)
        assert len(clipped) == 220
        assert clipped.endswith("…")

    def test_marker_distinguishes_dropped_from_complete(self) -> None:
        # The whole point: a clipped line must not look like a complete one.
        assert not clip("a" * 219, 220).endswith("…")
        assert clip("a" * 221, 220).endswith("…")


class TestGitFailureMessage:
    """The reason git gave must come before the argv it was given."""

    @pytest.fixture
    async def repo(self, tmp_path: Path) -> GitRepo:
        root = tmp_path / "proj"
        root.mkdir()
        repo = GitRepo(root)
        await repo.init()
        (root / "README.md").write_text("hello\n")
        await repo.add_all_and_commit("initial")
        return repo

    async def test_reason_precedes_argv(self, repo: GitRepo) -> None:
        with pytest.raises(WorkspaceError) as excinfo:
            await repo.worktree_add(
                repo.root / ".orkestra" / "worktrees" / "w", "br", "no-such-base-ref"
            )
        message = str(excinfo.value)
        assert "[argv:" in message
        # git's own words appear before the command it was handed.
        assert message.index("failed (exit") < message.index("[argv:")
        assert len(message.split("[argv:")[0]) > len("git worktree add failed (exit 128): ")

    async def test_reason_survives_the_console_budget(self, repo: GitRepo) -> None:
        """A deep worktree path must not push git's error past the clip."""
        deep = repo.root / ".orkestra" / "worktrees" / ("nested/" * 20 + "leaf")
        with pytest.raises(WorkspaceError) as excinfo:
            await repo.worktree_add(deep, "ork/run_deadbeef/task_cafebabe", "no-such-base")
        rendered = clip(str(excinfo.value).replace("\n", " "), 220)
        # This is the assertion the old format could not satisfy: with the argv
        # leading, 220 characters held nothing but the command.
        assert "fatal" in rendered or "invalid" in rendered.lower()

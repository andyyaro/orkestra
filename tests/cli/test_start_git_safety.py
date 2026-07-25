"""Git-safety regression suite for `orkestra start` (v0.4.1).

The invariant under test: **start never stages or commits files that
existed as uncommitted user work before the command began.** All
scenarios use real temporary Git repositories.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import orkestra.cli.start as start_module
from orkestra.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_detect() -> dict[str, dict[str, str]]:
        return {}

    monkeypatch.setattr(start_module, "_detect_ready_adapters", fake_detect)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def make_repo(root: Path, *, commit_readme: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    if commit_readme:
        (root / "README.md").write_text("# user project\n")
        git(root, "add", "README.md")
        git(root, "commit", "-q", "-m", "user baseline")


def start(root: Path, *extra: str) -> object:
    return runner.invoke(app, ["start", str(root), "--non-interactive", "--no-run", *extra])


def head_files(root: Path) -> list[str]:
    return [f for f in git(root, "show", "--name-only", "--format=", "HEAD").splitlines() if f]


class TestCleanScenarios:
    def test_1_clean_empty_directory(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        result = start(root)
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        # One-command experience preserved: repo created, setup committed.
        assert sorted(head_files(root)) == [".gitignore", "SPEC.md"]
        assert git(root, "status", "--porcelain").strip() == ""

    def test_2_clean_existing_repository(self, tmp_path: Path) -> None:
        root = tmp_path / "clean"
        make_repo(root)
        result = start(root)
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        # Setup commit contains only Orkestra-owned files (scenario 7/9).
        assert set(head_files(root)) <= {".gitignore", "SPEC.md"}
        assert "README.md" not in head_files(root)


class TestDirtyRepositoryStops:
    def test_3_modified_tracked_file_stops_before_mutation(self, tmp_path: Path) -> None:
        root = tmp_path / "dirty-tracked"
        make_repo(root)
        (root / "README.md").write_text("user edited this, uncommitted\n")
        result = start(root)
        assert result.exit_code == 1  # type: ignore[attr-defined]
        output = result.output  # type: ignore[attr-defined]
        # Plain language, no git jargon required to understand it.
        assert "work in progress" in output
        assert "git add -A" in output and "git stash" in output
        # Zero mutation: no SPEC.md, no .gitignore change, nothing staged.
        assert not (root / "SPEC.md").exists()
        assert not (root / ".orkestra").exists()
        assert git(root, "diff", "--name-only", "--cached").strip() == ""
        assert (root / "README.md").read_text().startswith("user edited")

    def test_4_staged_file_stops(self, tmp_path: Path) -> None:
        root = tmp_path / "dirty-staged"
        make_repo(root)
        (root / "half-done.py").write_text("wip = True\n")
        git(root, "add", "half-done.py")
        result = start(root)
        assert result.exit_code == 1  # type: ignore[attr-defined]
        assert "half-done.py" in result.output  # type: ignore[attr-defined]
        # Their staged file is still staged, untouched.
        assert "half-done.py" in git(root, "diff", "--name-only", "--cached")

    def test_10_noninteractive_dirty_is_deterministic(self, tmp_path: Path) -> None:
        root = tmp_path / "determin"
        make_repo(root)
        (root / "README.md").write_text("edit\n")
        first = start(root)
        second = start(root)
        assert first.exit_code == second.exit_code == 1  # type: ignore[attr-defined]
        assert "work in progress" in second.output  # type: ignore[attr-defined]


class TestUntrackedAndBaseline:
    def test_5_unrelated_untracked_files_proceed_but_never_committed(self, tmp_path: Path) -> None:
        root = tmp_path / "untracked"
        make_repo(root)
        (root / "scratch.txt").write_text("my notes\n")
        (root / "data.csv").write_text("1,2,3\n")
        result = start(root)
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        committed = head_files(root)
        assert "scratch.txt" not in committed and "data.csv" not in committed
        status = git(root, "status", "--porcelain")
        assert "?? scratch.txt" in status and "?? data.csv" in status  # untouched

    def test_6_new_repo_with_existing_files(self, tmp_path: Path) -> None:
        root = tmp_path / "newrepo"
        root.mkdir()
        (root / "app.py").write_text("print('existing user code')\n")
        (root / "notes.md").write_text("ideas\n")
        result = start(root)
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        output = result.output  # type: ignore[attr-defined]
        # Setup commit exists but contains ONLY Orkestra files...
        assert sorted(head_files(root)) == [".gitignore", "SPEC.md"]
        # ...user files remain uncommitted, with exact baseline guidance.
        status = git(root, "status", "--porcelain")
        assert "?? app.py" in status
        assert 'git add . && git commit -m "project baseline"' in output
        # and start refuses to auto-run without a baseline.
        assert "start the first run" not in output

    def test_8_nothing_unrelated_is_ever_staged(self, tmp_path: Path) -> None:
        root = tmp_path / "staging"
        make_repo(root)
        (root / "precious.txt").write_text("untracked user file\n")
        start(root)
        assert git(root, "diff", "--name-only", "--cached").strip() == ""
        status = git(root, "status", "--porcelain")
        assert "?? precious.txt" in status


class TestCompatibility:
    def test_11_existing_v04_project_still_usable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A project set up by the previous release keeps working:
        # start reconfigures it, and the run completes.
        root = tmp_path / "v04"
        result = start(root)
        assert result.exit_code == 0  # type: ignore[attr-defined]
        result = runner.invoke(
            app,
            ["start", str(root), "--non-interactive", "--preset", "faster", "--no-run"],
        )
        assert result.exit_code == 0, result.output
        monkeypatch.chdir(root)
        result = runner.invoke(app, ["run", "--offline"])
        assert result.exit_code == 0, result.output

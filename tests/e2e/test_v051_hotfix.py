"""v0.5.1 hotfix: staging must never fail on ignored artifacts, retry must
not dead-end on branch/worktree ordering, discarded work must be announced."""

from __future__ import annotations

from pathlib import Path

from orkestra.schemas.common import RunState, TaskState
from orkestra.workspace.git import GitRepo
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec


class TestStagingWithIgnoredArtifacts:
    async def test_commit_succeeds_when_gitignore_covers_artifacts(self, tmp_path: Path) -> None:
        """The v0.5.0 regression: `git add -A -- . :(exclude)__pycache__`
        hard-fails whenever .gitignore already ignores those paths."""
        repo_dir = tmp_path / "r"
        repo_dir.mkdir()
        repo = GitRepo(repo_dir)
        await repo.init()
        (repo_dir / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        await repo.add_all_and_commit("base")
        # an agent runs the tests, creating ignored artifacts
        (repo_dir / "__pycache__").mkdir()
        (repo_dir / "__pycache__" / "m.pyc").write_text("bytes")
        (repo_dir / "feature.py").write_text("x = 1\n")
        sha = await repo.add_all_and_commit("work")
        assert sha, "real work must be committed"
        _, tracked, _ = await repo._git("ls-files")
        assert "feature.py" in tracked
        assert "__pycache__" not in tracked

    async def test_artifacts_excluded_even_without_gitignore(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "r2"
        repo_dir.mkdir()
        repo = GitRepo(repo_dir)
        await repo.init()
        (repo_dir / "seed.txt").write_text("s\n")
        await repo.add_all_and_commit("base")
        (repo_dir / "__pycache__").mkdir()
        (repo_dir / "__pycache__" / "m.pyc").write_text("bytes")
        (repo_dir / "node_modules").mkdir()
        (repo_dir / "node_modules" / "z.js").write_text("z\n")
        (repo_dir / "app.py").write_text("y = 2\n")
        await repo.add_all_and_commit("work")
        _, tracked, _ = await repo._git("ls-files")
        assert "app.py" in tracked
        assert "__pycache__" not in tracked
        assert "node_modules" not in tracked

    async def test_run_completes_in_python_repo_with_gitignore(self, tmp_path: Path) -> None:
        """End-to-end: the regression made every task in such a repo fail."""
        app = await make_project(tmp_path)
        try:
            (app.root / ".gitignore").write_text(".orkestra/\n__pycache__/\n*.pyc\n")
            await GitRepo(app.root).add_all_and_commit("ignore artifacts")
            run_id = await manual_run(
                app,
                [(spec("t", "FAKE:write:mod.py:print(1)"), assign("alpha", "beta"))],
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.COMPLETE, "task must not be blocked by staging"
            repo = GitRepo(app.root)
            _, log, _ = await repo._git("log", "--oneline", f"ork/{run_id}/integration")
            assert log.strip(), "the result must actually be committed"
        finally:
            app.close()


class TestRetryDoesNotDeadEnd:
    async def test_workspace_recreated_after_block_and_retry(self, tmp_path: Path) -> None:
        """`git branch -D` used to fail because our own worktree held it."""
        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            workspace = await app.workspaces.create_workspace(run_id, "task_x")
            assert workspace.path.exists()
            # second creation with the branch still held must succeed
            again = await app.workspaces.create_workspace(run_id, "task_x")
            assert again.path.exists()
            assert await GitRepo(app.root).branch_exists(again.branch)
        finally:
            app.close()


class TestDiscardedWorkIsAnnounced:
    async def test_non_mutating_task_changes_are_reported(self, tmp_path: Path) -> None:
        from orkestra.schemas.common import TaskKind

        app = await make_project(tmp_path)
        try:
            run_id = await manual_run(
                app,
                [
                    (
                        spec("r", "FAKE:write:NOTES.md:hello", kind=TaskKind.RESEARCH),
                        assign("alpha", "beta"),
                    )
                ],
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.COMPLETE
            events = app.store.events_for_run(run_id, limit=1000)
            texts = " ".join(str(e["text"]) for e in events)
            assert "file changes are not kept" in texts
            assert "NOTES.md" in texts
        finally:
            app.close()


class TestBlockedTaskStateUnchanged:
    async def test_broken_gate_still_blocks(self, tmp_path: Path) -> None:
        """Regression guard: the v0.5.0 pre-flight must survive the hotfix."""
        from orkestra.app import build_app

        app = await make_project(tmp_path)
        config = app.root / ".orkestra" / "config.toml"
        config.write_text(
            config.read_text() + '\n[verify]\ncommands = ["definitely-not-a-binary-xyz --go"]\n'
        )
        app.close()
        app = build_app(app.root, offline=True)
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.WAITING_HUMAN
            task = app.store.tasks_for_run(run_id)[0]
            assert task.state is TaskState.BLOCKED
            assert app.store.attempts_for_task(task.task_id) == []
        finally:
            app.close()

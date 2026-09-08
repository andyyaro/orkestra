"""Integration tests: Git worktree lifecycle, policy checks, merging, recovery.

Real `git` repositories in tmp dirs; no network, no agents.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orkestra.errors import PolicyViolation, WorkspaceError
from orkestra.policy import PolicyEngine
from orkestra.schemas.config import PolicyConfig
from orkestra.workspace import GitRepo, WorkspaceManager
from orkestra.workspace.worktrees import Workspace


def make_policy() -> PolicyEngine:
    return PolicyEngine(PolicyConfig(), enabled_agents=["a", "b"])


@pytest.fixture
async def project(tmp_path: Path) -> WorkspaceManager:
    root = tmp_path / "proj"
    root.mkdir()
    repo = GitRepo(root)
    await repo.init()
    (root / "README.md").write_text("hello\n")
    await repo.add_all_and_commit("initial")
    return WorkspaceManager(root, make_policy())


class TestValidation:
    async def test_not_a_repo(self, tmp_path: Path) -> None:
        manager = WorkspaceManager(tmp_path, make_policy())
        with pytest.raises(WorkspaceError, match="not a Git repository"):
            await manager.validate_repository()

    async def test_no_commits(self, tmp_path: Path) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        await GitRepo(root).init()
        with pytest.raises(WorkspaceError, match="no commits"):
            await WorkspaceManager(root, make_policy()).validate_repository()

    async def test_tracked_changes_blocked(self, project: WorkspaceManager) -> None:
        (project.root / "README.md").write_text("modified tracked file")
        with pytest.raises(WorkspaceError, match="uncommitted changes"):
            await project.validate_repository()

    async def test_untracked_files_allowed(self, project: WorkspaceManager) -> None:
        # Agent CLIs drop state dirs (.claude/, logs); untracked files never
        # enter worktrees or merges, so they must not block runs.
        (project.root / "untracked.log").write_text("agent CLI state")
        await project.validate_repository()  # no raise


class TestRunAndWorkspaces:
    async def test_start_run_creates_integration_branch(self, project: WorkspaceManager) -> None:
        base, branch = await project.start_run("run_t1")
        assert branch == "ork/run_t1/integration"
        assert await project.repo.branch_exists(branch)
        assert base == await project.repo.head_commit()

    async def test_workspace_isolation(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t2")
        ws1 = await project.create_workspace("run_t2", "task_a1")
        ws2 = await project.create_workspace("run_t2", "task_b2")
        assert ws1.path != ws2.path
        (ws1.path / "one.txt").write_text("agent one\n")
        (ws2.path / "two.txt").write_text("agent two\n")
        # Mutations are invisible to each other and to the main checkout.
        assert not (ws2.path / "one.txt").exists()
        assert not (project.root / "one.txt").exists()

    async def test_commit_validate_integrate(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t3")
        ws = await project.create_workspace("run_t3", "task_c3")
        (ws.path / "feature.py").write_text("print('hi')\n")
        sha = await project.commit_workspace(ws, "add feature")
        assert sha is not None
        changed = await project.validate_workspace_changes(ws)
        assert changed == ["feature.py"]
        merged = await project.integrate("run_t3", ws, "feature")
        # integrate() returns the merge commit sha - the head of the
        # integration branch once the work has landed.
        integration_repo = GitRepo(project.root)
        assert merged == await integration_repo.rev_parse("ork/run_t3/integration")
        # File exists on the integration branch, not on main.
        _, out, _ = await integration_repo._git("show", "ork/run_t3/integration:feature.py")
        assert "hi" in out
        assert not (project.root / "feature.py").exists()

    async def test_clean_workspace_commit_returns_none(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t4")
        ws = await project.create_workspace("run_t4", "task_d4")
        assert await project.commit_workspace(ws, "nothing") is None

    async def test_protected_path_rejected(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t5")
        ws = await project.create_workspace("run_t5", "task_e5")
        hook_dir = ws.path / ".github" / "workflows"
        hook_dir.mkdir(parents=True)
        (hook_dir / "evil.yml").write_text("on: push\n")
        await project.commit_workspace(ws, "sneaky")
        with pytest.raises(PolicyViolation, match="protected path"):
            await project.validate_workspace_changes(ws)

    async def test_merge_conflict_detected_and_aborted(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t6")
        ws1 = await project.create_workspace("run_t6", "task_f6")
        ws2 = await project.create_workspace("run_t6", "task_g7")
        (ws1.path / "shared.txt").write_text("version A\n")
        (ws2.path / "shared.txt").write_text("version B\n")
        await project.commit_workspace(ws1, "A")
        await project.commit_workspace(ws2, "B")
        assert await project.integrate("run_t6", ws1, "first")
        merged = await project.integrate("run_t6", ws2, "second")
        assert merged is None  # conflict, aborted cleanly
        # Integration branch still has version A.
        out = await GitRepo(project.root).rev_parse("ork/run_t6/integration")
        assert out

    async def test_workspace_paths_with_spaces_and_unicode(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t7")
        ws = await project.create_workspace("run_t7", "task_h8")
        target = ws.path / "docs with space" / "übersicht.md"
        target.parent.mkdir(parents=True)
        target.write_text("unicode ok\n")
        await project.commit_workspace(ws, "unicode")
        changed = await project.validate_workspace_changes(ws)
        assert changed == ["docs with space/übersicht.md"]

    async def test_remove_workspace_preserves_or_deletes_branch(
        self, project: WorkspaceManager
    ) -> None:
        await project.start_run("run_t8")
        ws = await project.create_workspace("run_t8", "task_i9")
        await project.remove_workspace(ws, keep_branch=True)
        assert not ws.path.exists()
        assert await project.repo.branch_exists(ws.branch)
        # Recreate: stale branch must be replaced, not fail.
        ws2 = await project.create_workspace("run_t8", "task_i9")
        await project.remove_workspace(ws2, keep_branch=False)
        assert not await project.repo.branch_exists(ws2.branch)

    async def test_reconcile_reports_missing_worktrees(self, project: WorkspaceManager) -> None:
        await project.start_run("run_t9")
        ws = await project.create_workspace("run_t9", "task_j0")
        # Simulate crash: directory vanishes without unregistration.
        import shutil

        shutil.rmtree(ws.path)
        missing = await project.reconcile("run_t9", [str(ws.path)])
        assert missing == [str(ws.path)]


class TestGitSafety:
    async def test_refuses_to_delete_user_branches(self, project: WorkspaceManager) -> None:
        with pytest.raises(WorkspaceError, match="non-Orkestra branch"):
            await project.repo.delete_branch("main", force=True)

    async def test_hooks_disabled_for_orkestra_git(self, project: WorkspaceManager) -> None:
        hook = project.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho HOOK-RAN > hook-marker.txt\nexit 1\n")
        hook.chmod(0o755)
        (project.root / "x.txt").write_text("y")
        sha = await project.repo.add_all_and_commit("hook bypass check")
        assert sha is not None  # hook exit 1 would have blocked the commit
        assert not (project.root / "hook-marker.txt").exists()


class TestConcurrentWorktreeAdministration:
    """Concurrent worktree administration must complete and stay consistent.

    `git worktree add` builds .git/worktrees/<name>/ in steps, and
    `git worktree prune` deletes any entry that has no gitdir yet, so a prune
    landing inside another add's window kills it:

        fatal: could not open '.git/worktrees/<name>/locked' for writing:
        No such file or directory

    That is the cause of a macOS CI flake seen three times, in which a task
    blocked, the run stopped for a human decision, and the test reported only
    `assert 2 == 0`. It was observed in a stress run (1 in 200) and reproduced
    outside Orkestra at about 2.5% by running adds against concurrent prunes.

    This test does NOT reliably reproduce that race: through asyncio the
    subprocess spawns are staggered enough that it did not fire in 12 runs
    against the unserialized code. What it does guard is the fix itself. The
    serialization added to WorkspaceManager is a lock taken on paths that
    already nest inside _integration_lock, so the live risk is a deadlock or a
    stalled add, and this exercises exactly those paths concurrently.
    """

    async def test_adds_survive_concurrent_prunes(self, project: WorkspaceManager) -> None:
        import asyncio

        run_id = "run_race01"
        await project.start_run(run_id)

        # Stale registrations give the concurrent prune real work to do: a
        # prune with nothing to collect returns before it can race anything.
        doomed = [await project.create_workspace(run_id, f"task_p{i}") for i in range(5)]
        for workspace in doomed[:3]:
            shutil.rmtree(workspace.path)

        async def add(index: int) -> Workspace:
            return await project.create_workspace(run_id, f"task_a{index}")

        async def drop(workspace: Workspace) -> None:
            await project.remove_workspace(workspace, keep_branch=False)

        # Fire adds and remove+prune cycles at the same instant: this is the
        # overlap that git does not protect, and it raises WorkspaceError.
        created = await asyncio.gather(
            *(add(i) for i in range(8)),
            *(drop(w) for w in doomed),
        )

        # Every add that was asked for exists and is registered.
        workspaces = [w for w in created if isinstance(w, Workspace)]
        assert len(workspaces) == 8
        live = {str(Path(p).resolve()) for p in await project.repo.worktree_list()}
        for workspace in workspaces:
            assert workspace.path.exists()
            assert str(workspace.path.resolve()) in live


class TestUnlandedWork:
    """The guard's arming condition: committed, and not on the integration tip.

    It is asked of Git rather than of process state, so it answers the same
    after a resume, and it is about containment rather than about conflicts,
    so it covers every path that can strand a commit. It must also stay quiet
    when a retry legitimately produces nothing because the work already
    landed: a checker that halts a run on a correct configuration is the
    failure mode that gets checkers switched off.
    """

    async def test_quiet_when_the_task_never_committed(self, project: WorkspaceManager) -> None:
        run_id = "run_u1"
        await project.start_run(run_id)
        workspace = await project.create_workspace(run_id, "task_a1")
        assert await project.unlanded_work(run_id, "task_a1") is None
        await project.remove_workspace(workspace, keep_branch=False)
        assert await project.unlanded_work(run_id, "task_a1") is None

    async def test_quiet_when_the_work_landed(self, project: WorkspaceManager) -> None:
        run_id = "run_u2"
        await project.start_run(run_id)
        workspace = await project.create_workspace(run_id, "task_b2")
        (workspace.path / "feature.py").write_text("VALUE = 1\n")
        await project.commit_workspace(workspace, "add feature")
        merged = await project.integrate(run_id, workspace, "feature")
        assert merged is not None
        # This is the legitimate empty retry: nothing new, but nothing lost.
        assert await project.unlanded_work(run_id, "task_b2") is None

    async def test_speaks_when_a_commit_never_reached_integration(
        self, project: WorkspaceManager
    ) -> None:
        run_id = "run_u3"
        await project.start_run(run_id)
        workspace = await project.create_workspace(run_id, "task_c3")
        (workspace.path / "feature.py").write_text("VALUE = 2\n")
        sha = await project.commit_workspace(workspace, "work that will not land")
        assert sha is not None
        # Committed, never integrated: exactly what must not be reported done.
        unlanded = await project.unlanded_work(run_id, "task_c3")
        print(f"committed {sha[:12]}, unlanded_work reported {unlanded}")
        assert unlanded == sha

    async def test_a_retry_moves_the_previous_attempt_aside(
        self, project: WorkspaceManager
    ) -> None:
        """Recreating a workspace must not orphan the commits it held."""
        run_id = "run_u4"
        await project.start_run(run_id)
        first = await project.create_workspace(run_id, "task_d4")
        (first.path / "feature.py").write_text("VALUE = 3\n")
        sha = await project.commit_workspace(first, "attempt one")
        await project.remove_workspace(first, keep_branch=True)

        await project.create_workspace(run_id, "task_d4")  # the retry
        preserved = await project.repo.branches_with_prefix(first.branch)
        print(f"branches after retry: {preserved}")
        assert any(b != first.branch for b in preserved), "the attempt branch was not kept"
        assert await project.unlanded_work(run_id, "task_d4") == sha

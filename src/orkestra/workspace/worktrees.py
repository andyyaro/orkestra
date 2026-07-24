"""Worktree lifecycle and integration engine (ADR-0005).

Layout inside the project:

    .orkestra/worktrees/<run>-<task>-<suffix>/   per-task worktrees
    branch ork/<run>/<task>                       per-task branch
    branch ork/<run>/integration                  run integration branch

The user's own branches are never modified; results accumulate on the
integration branch, which the user merges deliberately.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from orkestra.errors import PolicyViolation, WorkspaceError
from orkestra.ids import branch_name, integration_branch, worktree_dirname
from orkestra.policy import PolicyEngine
from orkestra.workspace.git import GitRepo


@dataclass(frozen=True)
class Workspace:
    path: Path
    branch: str
    base_commit: str
    task_id: str


class WorkspaceManager:
    def __init__(self, project_root: Path, policy: PolicyEngine) -> None:
        self.root = Path(project_root).resolve()
        self.repo = GitRepo(self.root)
        self.policy = policy
        self.worktrees_dir = self.root / ".orkestra" / "worktrees"
        # The integration branch can host only one merge worktree at a time;
        # concurrent task completions must take turns.
        self._integration_lock = asyncio.Lock()

    # ---------------------------------------------------------- checks

    async def validate_repository(self, *, allow_dirty: bool = False) -> None:
        if not await self.repo.is_repo():
            msg = f"{self.root} is not a Git repository — run `git init` or `orkestra init` first"
            raise WorkspaceError(msg)
        if not await self.repo.has_commits():
            msg = (
                "repository has no commits; Orkestra needs a base commit "
                "(`orkestra init` creates one)"
            )
            raise WorkspaceError(msg)
        if not allow_dirty:
            # Tracked modifications could entangle user work with agent work;
            # untracked files are safe (worktrees and merges never include
            # them) — agent CLIs routinely drop state dirs like .claude/.
            changed = await self.repo.tracked_changes()
            if changed:
                listing = ", ".join(changed[:5])
                msg = (
                    f"repository has uncommitted changes to tracked files "
                    f"({listing}); commit or stash them before starting a run "
                    "(Orkestra will not touch dirty state)"
                )
                raise WorkspaceError(msg)

    # ------------------------------------------------------------ runs

    async def start_run(self, run_id: str) -> tuple[str, str]:
        """Create the integration branch; returns (base_commit, branch)."""
        await self.validate_repository()
        base = await self.repo.head_commit()
        branch = integration_branch(run_id)
        if await self.repo.branch_exists(branch):
            msg = f"integration branch {branch} already exists"
            raise WorkspaceError(msg)
        await self.repo.create_branch(branch, base)
        return base, branch

    # ------------------------------------------------------- worktrees

    async def create_workspace(self, run_id: str, task_id: str) -> Workspace:
        """New worktree branched from the current integration branch head."""
        integration = integration_branch(run_id)
        if not await self.repo.branch_exists(integration):
            msg = f"integration branch missing for run {run_id}"
            raise WorkspaceError(msg)
        base = await self.repo.rev_parse(integration)
        branch = branch_name(run_id, task_id)
        if await self.repo.branch_exists(branch):
            # A previous interrupted attempt left the branch; make a fresh one.
            await self.repo.delete_branch(branch, force=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_dir / worktree_dirname(run_id, task_id)
        await self.repo.worktree_add(path, branch, base)
        return Workspace(path=path, branch=branch, base_commit=base, task_id=task_id)

    async def commit_workspace(self, workspace: Workspace, message: str) -> str | None:
        """Deterministically commit whatever the agent changed (or None)."""
        wt = GitRepo(workspace.path)
        return await wt.add_all_and_commit(message)

    async def validate_workspace_changes(self, workspace: Workspace) -> list[str]:
        """Return changed paths after policy validation; raise on violation."""
        wt = GitRepo(workspace.path)
        changed = await wt.changed_paths(workspace.base_commit)
        decision = self.policy.check_diff_paths(changed)
        if not decision.allowed:
            msg = "; ".join(decision.violations)
            raise PolicyViolation(msg)
        return changed

    async def integrate(self, run_id: str, workspace: Workspace, title: str) -> bool:
        """Merge the task branch into the integration branch (no-ff).

        Returns False on merge conflict (workspace preserved for
        inspection and replanning).
        """
        integration = integration_branch(run_id)
        async with self._integration_lock:
            # Merge in a worktree of the integration branch to avoid touching
            # the user's checkout; serialized because a branch can host only
            # one worktree at a time.
            merge_dir = self.worktrees_dir / f"integrate-{worktree_dirname(run_id, 'merge')}"
            await self.repo.worktree_add_existing(merge_dir, integration)
            try:
                merge_repo = GitRepo(merge_dir)
                return await merge_repo.merge_no_ff(
                    workspace.branch,
                    f"orkestra: integrate {title} ({workspace.task_id})",
                )
            finally:
                await self.repo.worktree_remove(merge_dir, force=True)
                await self.repo.worktree_prune()

    async def remove_workspace(self, workspace: Workspace, *, keep_branch: bool) -> None:
        if workspace.path.exists():
            await self.repo.worktree_remove(workspace.path, force=True)
        await self.repo.worktree_prune()
        if not keep_branch and await self.repo.branch_exists(workspace.branch):
            await self.repo.delete_branch(workspace.branch, force=True)

    # ------------------------------------------------------- recovery

    async def reconcile(self, run_id: str, recorded_paths: list[str]) -> list[str]:
        """Repair worktree state after a crash.

        Prunes stale registrations and reports recorded paths that no
        longer exist so the kernel can re-plan those tasks.
        """
        await self.repo.worktree_prune()
        live = {Path(p).resolve() for p in await self.repo.worktree_list()}
        return [p for p in recorded_paths if Path(p).resolve() not in live]

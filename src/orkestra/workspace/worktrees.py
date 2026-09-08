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
import contextlib
import secrets
from collections.abc import AsyncIterator
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
        # `git worktree add` builds .git/worktrees/<name>/ in steps, and
        # `git worktree prune` deletes any entry that has no gitdir yet. A
        # prune that lands inside another add's window therefore kills it:
        #   fatal: could not open '.git/worktrees/<name>/locked' for writing
        # Git does not serialize these for us, so the administrative commands
        # take turns here. They are short; the agent work they bracket is not
        # held up by this.
        self._worktree_admin = asyncio.Lock()

    # ---------------------------------------------------------- checks

    async def validate_repository(self, *, allow_dirty: bool = False) -> None:
        if not await self.repo.is_repo():
            msg = f"{self.root} is not a Git repository - run `git init` or `orkestra init` first"
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
            # them) - agent CLIs routinely drop state dirs like .claude/.
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
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_dir / worktree_dirname(run_id, task_id)
        async with self._worktree_admin:
            if await self.repo.branch_exists(branch):
                # A previous attempt left the branch. Its worktree (if any) must
                # be removed FIRST: git refuses to delete a branch a worktree
                # still holds, which would dead-end the retry path.
                prefix = f"{run_id}-{task_id}-"
                for existing in await self.repo.worktree_list():
                    candidate = Path(existing)
                    if candidate.name.startswith(prefix):
                        with contextlib.suppress(WorkspaceError):
                            await self.repo.worktree_remove(candidate, force=True)
                await self.repo.worktree_prune()
                # A previous attempt's branch may be the only thing holding
                # its commits. Deleting it orphans them, and an orphaned
                # commit is indistinguishable from work that was never done,
                # so move it aside instead and let unlanded_work find it.
                if await self._holds_work(branch, base):
                    with contextlib.suppress(WorkspaceError):
                        await self.repo.rename_branch(
                            branch, f"{branch}-attempt-{secrets.token_hex(3)}"
                        )
                else:
                    with contextlib.suppress(WorkspaceError):
                        await self.repo.delete_branch(branch, force=True)
                if await self.repo.branch_exists(branch):
                    # Still held (e.g. by a worktree outside our directory):
                    # use a fresh name rather than dead-ending the retry.
                    branch = f"{branch}-{secrets.token_hex(3)}"
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

    async def integrate(self, run_id: str, workspace: Workspace, title: str) -> str | None:
        """Merge the task branch into the integration branch (no-ff).

        Returns the merge commit sha, or None on merge conflict
        (workspace preserved for inspection and replanning).
        """
        integration = integration_branch(run_id)
        async with self._integration_lock:
            # Merge in a worktree of the integration branch to avoid touching
            # the user's checkout; serialized because a branch can host only
            # one worktree at a time.
            merge_dir = self.worktrees_dir / f"integrate-{worktree_dirname(run_id, 'merge')}"
            async with self._worktree_admin:
                await self.repo.worktree_add_existing(merge_dir, integration)
            try:
                merge_repo = GitRepo(merge_dir)
                return await merge_repo.merge_no_ff(
                    workspace.branch,
                    f"orkestra: integrate {title} ({workspace.task_id})",
                )
            finally:
                async with self._worktree_admin:
                    await self.repo.worktree_remove(merge_dir, force=True)
                    await self.repo.worktree_prune()

    @contextlib.asynccontextmanager
    async def scratch_worktree(self, purpose: str, ref: str | None = None) -> AsyncIterator[Path]:
        """A throwaway detached worktree, removed however the body exits.

        Detached on purpose: a branch can host only one worktree, and this
        must never contend with the integration merge worktree. Used to run
        checks (the gate binding canary, `orkestra doctor`) against a real
        checkout without touching the user's tree or any task's tree.
        """
        target = ref or await self.repo.head_commit()
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_dir / f"scratch-{worktree_dirname(purpose, 'wt')}"
        async with self._worktree_admin:
            await self.repo.worktree_add_existing(path, target)
        try:
            yield path
        finally:
            async with self._worktree_admin:
                with contextlib.suppress(WorkspaceError):
                    await self.repo.worktree_remove(path, force=True)
                await self.repo.worktree_prune()

    async def _holds_work(self, branch: str, base: str) -> bool:
        """True if *branch* has commits beyond *base*."""
        if not await self.repo.branch_exists(branch):
            return False
        return await self.repo.rev_parse(branch) != base

    async def unlanded_work(self, run_id: str, task_id: str) -> str | None:
        """Sha of work this task committed that is not on the integration branch.

        Read from git rather than from process state, so it survives a
        resume: the question "did this task produce a commit that never
        landed" has the same answer in a fresh process as in the one that
        made the commit.
        """
        integration = integration_branch(run_id)
        if not await self.repo.branch_exists(integration):
            return None
        prefix = branch_name(run_id, task_id)
        for candidate in await self.repo.branches_with_prefix(prefix):
            head = await self.repo.rev_parse(candidate)
            if head != await self.repo.merge_base(candidate, integration):
                # Not an ancestor of the integration tip: it never landed.
                return head
        return None

    async def remove_workspace(self, workspace: Workspace, *, keep_branch: bool) -> None:
        async with self._worktree_admin:
            if workspace.path.exists():
                await self.repo.worktree_remove(workspace.path, force=True)
            await self.repo.worktree_prune()
        if keep_branch or not await self.repo.branch_exists(workspace.branch):
            return
        # A branch holding commits is the only copy of that work once its
        # worktree is gone. Deleting it orphans the commit, and an orphaned
        # commit is indistinguishable from work that was never done.
        head = await self.repo.rev_parse(workspace.branch)
        if head != workspace.base_commit:
            return
        await self.repo.delete_branch(workspace.branch, force=True)

    # ------------------------------------------------------- recovery

    async def reconcile(self, run_id: str, recorded_paths: list[str]) -> list[str]:
        """Repair worktree state after a crash.

        Prunes stale registrations and reports recorded paths that no
        longer exist so the kernel can re-plan those tasks.
        """
        async with self._worktree_admin:
            await self.repo.worktree_prune()
            live = {Path(p).resolve() for p in await self.repo.worktree_list()}
        return [p for p in recorded_paths if Path(p).resolve() not in live]

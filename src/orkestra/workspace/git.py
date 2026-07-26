"""Safe Git command execution.

Every Git call: argument arrays, hooks disabled (``core.hooksPath=``),
no shell, bounded output, explicit errors. Branch and path inputs are
kernel-generated (see :mod:`orkestra.ids`); user/agent text never
becomes a Git argument (threats T1, T8, T10).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from orkestra.errors import WorkspaceError
from orkestra.verify.runner import subprocess_env

_GIT_TIMEOUT_S = 120.0


class GitRepo:
    """Wrapper for one repository root (main checkout or a worktree)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    async def _git(
        self, *args: str, check: bool = True, timeout_s: float = _GIT_TIMEOUT_S
    ) -> tuple[int, str, str]:
        argv = [
            "git",
            "-c",
            "core.hooksPath=",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "advice.detachedHead=false",
            *args,
        ]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.root),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env(
                {
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_AUTHOR_NAME": "Orkestra",
                    "GIT_AUTHOR_EMAIL": "orkestra@localhost",
                    "GIT_COMMITTER_NAME": "Orkestra",
                    "GIT_COMMITTER_EMAIL": "orkestra@localhost",
                }
            ),
            start_new_session=True,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            msg = f"git {' '.join(args[:2])} timed out after {timeout_s}s"
            raise WorkspaceError(msg) from exc
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        code = proc.returncode if proc.returncode is not None else -1
        if check and code != 0:
            msg = f"git {' '.join(args)} failed (exit {code}): {stderr.strip()[:500]}"
            raise WorkspaceError(msg)
        return code, stdout, stderr

    # ------------------------------------------------------------ state

    async def is_repo(self) -> bool:
        code, out, _ = await self._git("rev-parse", "--is-inside-work-tree", check=False)
        return code == 0 and out.strip() == "true"

    async def toplevel(self) -> Path | None:
        """Root of the repository containing this directory, if any."""
        code, out, _ = await self._git("rev-parse", "--show-toplevel", check=False)
        return Path(out.strip()).resolve() if code == 0 and out.strip() else None

    async def head_commit(self, ref: str = "HEAD") -> str:
        _, out, _ = await self._git("rev-parse", ref)
        return out.strip()

    async def has_commits(self) -> bool:
        code, _, _ = await self._git("rev-parse", "--verify", "HEAD", check=False)
        return code == 0

    async def is_dirty(self) -> bool:
        _, out, _ = await self._git("status", "--porcelain")
        return bool(out.strip())

    async def tracked_changes(self) -> list[str]:
        """Modified/staged/deleted tracked paths (untracked excluded)."""
        _, out, _ = await self._git("status", "--porcelain")
        return [line[3:] for line in out.splitlines() if line.strip() and not line.startswith("??")]

    async def untracked_files(self) -> list[str]:
        _, out, _ = await self._git("status", "--porcelain")
        return [line[3:] for line in out.splitlines() if line.startswith("??")]

    async def staged_changes(self) -> list[str]:
        """Paths with staged (index) changes."""
        _, out, _ = await self._git("status", "--porcelain")
        return [
            line[3:] for line in out.splitlines() if line[:1] not in (" ", "?", "") and line.strip()
        ]

    async def current_branch(self) -> str:
        _, out, _ = await self._git("rev-parse", "--abbrev-ref", "HEAD")
        return out.strip()

    async def branch_exists(self, branch: str) -> bool:
        code, _, _ = await self._git("show-ref", "--verify", f"refs/heads/{branch}", check=False)
        return code == 0

    # ------------------------------------------------------- lifecycle

    async def init(self, initial_branch: str = "main") -> None:
        await self._git("init", "-b", initial_branch)

    async def create_branch(self, branch: str, at: str) -> None:
        await self._git("branch", branch, at)

    async def delete_branch(self, branch: str, force: bool = False) -> None:
        if not branch.startswith("ork/"):
            msg = f"refusing to delete non-Orkestra branch {branch!r}"
            raise WorkspaceError(msg)
        await self._git("branch", "-D" if force else "-d", branch)

    async def checkout(self, ref: str) -> None:
        await self._git("checkout", ref)

    async def commit_paths(self, paths: list[str], message: str) -> str | None:
        """Stage and commit ONLY *paths* (pathspec-scoped; the user's other
        staged or modified files are untouched). Returns sha or None when
        none of the paths have changes."""
        if not paths:
            return None
        _, status, _ = await self._git("status", "--porcelain", "--", *paths)
        if not status.strip():
            return None
        await self._git("add", "--", *paths)
        await self._git("commit", "-m", message, "--", *paths)
        return await self.head_commit()

    async def commit_files_in(self, ref: str = "HEAD") -> list[str]:
        """Files contained in a commit (for allowlist verification)."""
        _, out, _ = await self._git("show", "--name-only", "--format=", ref)
        return [line for line in out.splitlines() if line.strip()]

    #: Build artifacts agent test runs generate. Excluded defensively for
    #: projects whose .gitignore doesn't cover them; never via `git add`
    #: pathspecs, which turn ignored paths into a hard error.
    _ARTIFACTS = ("__pycache__", "*.pyc", "node_modules", ".pytest_cache", ".ruff_cache")

    async def add_all_and_commit(self, message: str) -> str | None:
        """Stage everything and commit; returns commit sha or None if clean.

        `git add -A` with no pathspec silently skips ignored files; adding
        `:(exclude)` pathspecs would make git *fail* whenever an ignored
        path exists (v0.5.0 regression). Artifacts that slip through are
        unstaged afterwards instead.
        """
        await self._git("add", "-A")
        await self._git(
            "rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *self._ARTIFACTS, check=False
        )
        _, out, _ = await self._git("status", "--porcelain")
        staged = [line for line in out.splitlines() if line[:1] not in (" ", "?", "")]
        if not staged:
            return None
        await self._git("commit", "-m", message)
        return await self.head_commit()

    # ------------------------------------------------------- worktrees

    async def rev_parse(self, ref: str) -> str:
        _, out, _ = await self._git("rev-parse", ref)
        return out.strip()

    async def worktree_add_existing(self, path: Path, ref: str) -> None:
        """Add a worktree checked out at an existing ref (no new branch)."""
        await self._git("worktree", "add", str(path), ref)

    async def worktree_add(self, path: Path, branch: str, base: str) -> None:
        if path.exists():
            msg = f"worktree path already exists: {path}"
            raise WorkspaceError(msg)
        await self._git("worktree", "add", "-b", branch, str(path), base)

    async def worktree_remove(self, path: Path, force: bool = False) -> None:
        args = ["worktree", "remove", str(path)]
        if force:
            args.insert(2, "--force")
        await self._git(*args)

    async def worktree_prune(self) -> None:
        await self._git("worktree", "prune")

    async def worktree_list(self) -> list[str]:
        _, out, _ = await self._git("worktree", "list", "--porcelain")
        return [
            line.removeprefix("worktree ").strip()
            for line in out.splitlines()
            if line.startswith("worktree ")
        ]

    # ------------------------------------------------------ inspection

    async def changed_paths(self, base: str, head: str = "HEAD") -> list[str]:
        _, out, _ = await self._git("diff", "--name-only", "-z", f"{base}..{head}")
        return [p for p in out.split("\0") if p]

    async def diff_stat(self, base: str, head: str = "HEAD") -> str:
        _, out, _ = await self._git("diff", "--stat", f"{base}..{head}")
        return out.strip()

    async def commits_between(self, base: str, head: str = "HEAD") -> list[str]:
        _, out, _ = await self._git("rev-list", f"{base}..{head}")
        return [line for line in out.splitlines() if line.strip()]

    # ------------------------------------------------------ integration

    async def merge_no_ff(self, branch: str, message: str) -> str | None:
        """Merge *branch*; the merge commit sha on success, None on
        conflict (aborted). The sha is what downstream consumers (reports,
        memory systems) need to anchor "this work actually landed"."""
        code, stdout, stderr = await self._git(
            "merge", "--no-ff", "-m", message, branch, check=False
        )
        if code == 0:
            _, sha, _ = await self._git("rev-parse", "HEAD")
            return sha.strip()
        await self._git("merge", "--abort", check=False)
        combined = (stdout + stderr).lower()
        if "conflict" in combined or "automatic merge failed" in combined:
            return None
        msg = f"merge of {branch} failed unexpectedly: {(stderr or stdout).strip()[:500]}"
        raise WorkspaceError(msg)

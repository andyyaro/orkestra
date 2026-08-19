# ADR-0005: Workspace isolation - Git worktrees per mutable task

Date: 2026-07-24 · Status: accepted

## Context

Two agents must never mutate the same checkout; failed work must be
inspectable; integration must be explicit and verified.

## Decision

Each mutable task runs in `git worktree add
.orkestra/worktrees/<run>-<task>-<suffix> -b ork/<run>/<task>` from a
recorded base commit on the run's integration branch
(`ork/<run>/integration`). Integration is a kernel-performed `merge
--no-ff` into the integration branch after gates and review pass; the
user's own branches are never touched automatically. All Orkestra Git
commands run hook-disabled (`-c core.hooksPath=`) via argument arrays.

Docker-based isolation is an additional opt-in layer around the same
worktree, not a replacement.

## Rationale

- Worktrees share the object store (cheap), give real filesystem
  isolation between tasks, and preserve failed branches for forensics.
- An integration branch keeps the user's `main` untouched until the
  user merges the run result deliberately.

## Consequences

- Repositories without commits need an initial commit (init flow
  handles this). Dirty repositories block run start (explicit error).
- Worktree state is reconciled on resume: registered-but-missing or
  orphaned worktrees are detected and repaired/pruned.

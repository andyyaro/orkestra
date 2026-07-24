"""Identifier generation and name validation.

All Git-facing names (branches, worktree directories) are generated here
from a restricted alphabet; external input never becomes a Git reference
(threat T1/T9 in the threat model).
"""

from __future__ import annotations

import re
import secrets

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REF_COMPONENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def new_id(prefix: str) -> str:
    """Return a short unique identifier such as ``task_3f9a1c2b``."""
    return f"{prefix}_{secrets.token_hex(4)}"


def is_valid_slug(value: str) -> bool:
    """True if *value* is a safe lowercase slug (agent names, task keys)."""
    return bool(_SLUG_RE.match(value))


def require_slug(value: str, what: str) -> str:
    """Validate *value* as a slug, raising ``ValueError`` otherwise."""
    if not is_valid_slug(value):
        msg = (
            f"{what} {value!r} is not a valid identifier: use 1-64 chars of "
            "lowercase letters, digits, '.', '_' or '-', starting with a letter or digit"
        )
        raise ValueError(msg)
    return value


def branch_name(run_id: str, task_id: str) -> str:
    """Deterministic, injection-safe branch name for a task attempt."""
    for component in (run_id, task_id):
        if not _REF_COMPONENT_RE.match(component):
            msg = f"internal id {component!r} failed reference validation"
            raise ValueError(msg)
    return f"ork/{run_id}/{task_id}"


def integration_branch(run_id: str) -> str:
    """Branch that accumulates verified task results for a run."""
    if not _REF_COMPONENT_RE.match(run_id):
        msg = f"internal id {run_id!r} failed reference validation"
        raise ValueError(msg)
    return f"ork/{run_id}/integration"


def worktree_dirname(run_id: str, task_id: str) -> str:
    """Unique directory name for a task worktree (collision-safe suffix)."""
    return f"{run_id}-{task_id}-{secrets.token_hex(3)}"

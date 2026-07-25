"""Plain-language explanations for human gates and hard failures.

The kernel speaks precisely; humans deserve a translation. Each entry:
what happened → what it usually means → what to try first.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orkestra.store.repo import AttemptRow


def _dominant_error(attempts: list[AttemptRow]) -> str:
    kinds = [a.result.error_kind.value for a in attempts if a.result is not None]
    if not kinds:
        return ""
    return Counter(kinds).most_common(1)[0][0]


def explain_block(reason: str, attempts: list[AttemptRow] | None = None) -> str:
    """One short paragraph a non-expert can act on."""
    lower = reason.lower()
    dominant = _dominant_error(attempts or [])

    if "review cycles exhausted" in lower or "review/fix cycle" in lower:
        return (
            "The reviewing agent kept requesting changes and the allowed "
            "fix rounds ran out. This usually means the task description or "
            "SPEC.md is ambiguous enough that implementer and reviewer "
            "disagree about 'done'. Sharpen the acceptance criteria, or "
            "raise policy.max_review_cycles, then choose 'retry'."
        )
    if "no independent reviewer" in lower:
        return (
            "A different agent must approve every change, and none of the "
            "other agents produced a usable verdict (errors or malformed "
            "responses). Check `orkestra doctor` for agent health, or — if "
            "you accept the risk — set policy.require_review = false."
        )
    if "verification setup error" in lower or ("not found" in lower and "command" in lower):
        return (
            "An acceptance command could not even start (it is not an "
            "executable command on PATH). Fix [verify] commands in "
            ".orkestra/config.toml — each entry must run as-is in a fresh "
            "checkout — then choose 'retry'."
        )
    if "policy violation" in lower or "protected path" in lower:
        return (
            "An agent's changes touched files Orkestra protects (like CI "
            "workflows or .git). Usually the task description pointed the "
            "agent somewhere it shouldn't go — adjust the task/spec "
            "boundaries, or policy.protected_paths if this was intended."
        )
    if "workspace error" in lower:
        return (
            "A Git operation failed while managing this task's isolated "
            "worktree. Check `git status` and `git worktree list` in your "
            "repository; after fixing, choose 'retry'."
        )
    if "token budget" in lower:
        return (
            "Every remaining agent has spent its per-run token budget "
            "(agents.<name>.token_budget). Raise the budgets, or choose "
            "'retry' to reset this task's counters and continue anyway."
        )
    if "exhausted" in lower or "failed with all available agents" in lower:
        hints = {
            "auth": (
                "Attempts mostly failed with authentication errors — an "
                "agent CLI is signed out. Run `orkestra doctor`, sign in "
                "with the vendor's own command, then choose 'retry'."
            ),
            "rate_limit": (
                "Attempts mostly hit provider rate limits — your plan's "
                "window is likely exhausted. Wait for it to reset (pausing "
                "is safe), then choose 'retry'."
            ),
            "timeout": (
                "Attempts mostly timed out. The task may be too big for one "
                "sitting — split it in the spec, or raise "
                "policy.task_timeout_s, then choose 'retry'."
            ),
            "invalid_output": (
                "Agents finished but their output could not be used. This "
                "is often transient; 'retry' is usually worth one shot."
            ),
        }
        if dominant in hints:
            return hints[dominant]
        return (
            "Every eligible agent tried this task and failed, most often "
            "because acceptance commands keep failing (check they pass in a "
            "fresh checkout: missing dependencies are the classic cause) or "
            "the task is under-specified. Fix, then choose 'retry'."
        )
    if "pipeline crash" in lower:
        return (
            "Something unexpected broke while processing this task — this "
            "is more likely an Orkestra or environment issue than an agent "
            "one. The details above matter; a bug report with `orkestra "
            "report --out report.md` attached is welcome."
        )
    return (
        "Orkestra could not resolve this automatically within its safety "
        "budgets. Review the details above; 'retry' resets the task's "
        "budgets after you address the cause."
    )

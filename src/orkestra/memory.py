"""Optional verified memory, backed by Provalume.

Orkestra produces exactly what a verification-grounded memory system needs and
throws most of it away: which command passed, which reviewer approved, which
commit landed, which approach failed and what worked instead. This module hands
that to Provalume and splices a bounded digest back into the task brief.

**Provalume is optional.** Without it installed, :func:`open_memory` returns
``None`` and every call site here is a no-op — Orkestra behaves exactly as it did
before. That is not politeness; it keeps the kernel's dependency footprint and
its failure modes unchanged for users who do not want memory.

Three rules govern this module:

1. **Memory never overrides policy.** The pre-action gate returns a warning that
   is appended to a brief. It cannot block a dispatch, change a retry budget, or
   veto an assignment. Orkestra's policy engine remains the only authority — a
   memory-poisoning bug must not become an orchestration-control bug.

2. **Retrieval fails open; a memory outage is not a run outage.** Every call here
   is wrapped, and a failure degrades to "no context available".

3. **Nothing Provalume returns is trusted input.** Digests are labelled untrusted
   reference data by Provalume itself and are appended *after* the task
   instructions, never before.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from orkestra.schemas.config import ProjectConfig
    from orkestra.schemas.task import TaskSpec

#: Recorded once so `doctor` and the run report can say whether memory is active.
_UNAVAILABLE_REASON = ""


def is_available() -> bool:
    """Whether Provalume is importable."""
    global _UNAVAILABLE_REASON
    try:
        import provalume  # noqa: F401
    except ImportError as exc:
        _UNAVAILABLE_REASON = str(exc)
        return False
    return True


def unavailable_reason() -> str:
    """Why memory is off, for `doctor` output. Empty when it is available."""
    if is_available():
        return ""
    return _UNAVAILABLE_REASON or "provalume is not installed"


class Memory:
    """A thin bridge between Orkestra's kernel and Provalume.

    Holds a Provalume client and an adapter. Every public method swallows
    failures and returns a safe default, because the kernel must never fail a run
    because memory misbehaved.
    """

    def __init__(self, adapter: Any, client: Any) -> None:
        self._adapter = adapter
        self._client = client

    # -- reading -----------------------------------------------------------

    def brief_context(self, *, title: str, task_id: str, budget: int = 2000) -> str:
        """A budgeted digest to splice into a task brief, or ``""``.

        Returns a string rather than a digest object so the caller can append it
        without knowing anything about Provalume's types.
        """
        try:
            from provalume.integrations.generic import splice_digest
            from provalume.integrations.orkestra import safe_digest

            digest = safe_digest(self._adapter, query=title, char_budget=budget, task_id=task_id)
            if digest is None or not digest.items:
                return ""
            # Annotated rather than returned directly: Provalume is an optional
            # extra, so under a type-check without it installed everything
            # crossing this boundary is `Any`. Naming the type here is what keeps
            # the rest of the module strict.
            spliced: str = splice_digest("", digest)
            return spliced.strip()
        except Exception:
            return ""

    def preflight_warning(self, *, spec: TaskSpec) -> str:
        """A warning if this task resembles a known failure, or ``""``.

        **Advisory only.** The caller appends it to the brief; nothing here can
        block a dispatch.
        """
        try:
            from provalume.integrations.orkestra import safe_preflight

            command = spec.acceptance[0] if spec.acceptance else ""
            result = safe_preflight(self._adapter, command=command, subsystem=spec.kind.value)
            if result is None or not result.matched:
                return ""
            summary: str = result.summary
            return summary
        except Exception:
            return ""

    # -- writing -----------------------------------------------------------

    def record_verification(
        self,
        *,
        command: str,
        passed: bool,
        excerpt: str,
        task_id: str,
        attempt_id: str | None = None,
        agent: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """The most valuable thing Orkestra can supply.

        A failure becomes a gotcha keyed on a deterministic signature; a success
        becomes a procedural candidate keyed on the exact command.

        A success also names the failure it resolves, when there is one. Without
        that, resolution is only inferred within a single task or run — and
        Orkestra's real recovery path is to block a task, escalate to a human,
        and do the work in a *later* run. The failure and its fix therefore land
        in different runs, nothing links them, and the gate goes on warning about
        something that was fixed.
        """
        resolves = self._unresolved_signature(command) if passed else ""
        self._safe(
            lambda: self._adapter.verification(
                command=command,
                passed=passed,
                exit_code=exit_code,
                excerpt=excerpt[:8000],
                task_id=task_id,
                attempt_id=attempt_id,
                agent=agent,
                resolves_signature=resolves,
            )
        )

    def _unresolved_signature(self, command: str) -> str:
        """The signature of an unresolved prior failure of this command, if any.

        Read through the same pre-action gate the brief uses, so a success is
        matched to a failure by exactly the criteria that would have warned about
        it. Returns "" on any failure or no match — linking a resolution is an
        improvement, never a precondition for recording the success.
        """
        try:
            from provalume.integrations.orkestra import safe_preflight

            # record=False: this is a lookup, not a warning shown to anyone.
            # Recording here would inflate the warning count that warning
            # usefulness is measured from.
            result = safe_preflight(self._adapter, command=command, record=False)
            if result is None or not result.matched:
                return ""
            for match in result.matches:
                if not match.what_later_worked and match.failure_signature:
                    return str(match.failure_signature)
            return ""
        except Exception:
            return ""

    def record_review(
        self,
        *,
        reviewer: str,
        approved: bool,
        subject: str,
        finding: str = "",
        task_id: str,
        attempt_id: str | None = None,
    ) -> None:
        """Record a review verdict.

        Orkestra keeps verdicts inside ``attempts.result`` JSON rather than in a
        dedicated table, so this is an explicit call at the point the verdict is
        produced. The reviewer's identity matters: Provalume compares it against
        the record's author and refuses to promote on a self-review.
        """
        self._safe(
            lambda: self._adapter.review_verdict(
                reviewer=reviewer,
                approved=approved,
                subject=subject,
                finding=finding[:4000],
                task_id=task_id,
                attempt_id=attempt_id,
            )
        )

    def record_integration(self, *, commit_sha: str, task_id: str) -> None:
        """Record that work landed — what semantic truth requires."""
        self._safe(
            lambda: self._adapter.integration_landed(
                commit_sha=commit_sha, target="run", task_id=task_id
            )
        )

    def record_attempt(
        self,
        *,
        task_id: str,
        attempt_id: str,
        outcome: str,
        kind: str,
        agent: str,
        adapter_id: str = "",
        model: str = "",
        error_kind: str = "",
    ) -> None:
        """Feed performance memory: which agent profile succeeds at what."""
        self._safe(
            lambda: self._adapter.attempt_completed(
                task_id=task_id,
                attempt_id=attempt_id,
                outcome=outcome,
                error_kind=error_kind or None,
                agent=agent,
                adapter=adapter_id or None,
                model=model or None,
                kind=kind,
            )
        )

    def record_decision(
        self,
        *,
        question: str,
        selected: str,
        rejected: tuple[str, ...] = (),
        note: str = "",
    ) -> None:
        """Record a resolved human decision gate.

        ``rejected`` is the reusable part: without it, nothing stops an agent
        re-proposing what a human already turned down.
        """
        self._safe(
            lambda: self._adapter.human_decision(
                question=question,
                selected=selected,
                rejected=rejected,
                rationale=note,
                authority="human",
            )
        )

    def record_run_completed(self, *, run_id: str, outcome: str, tasks: int) -> None:
        self._safe(
            lambda: self._adapter.run_completed(run_id=run_id, outcome=outcome, task_count=tasks)
        )

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._safe(self._client.close)

    @staticmethod
    def _safe(call: Any) -> None:
        """Run a write, swallowing any failure.

        Writes are best-effort by design. An orchestration run must not fail
        because a memory write did — and a partial write cannot corrupt anything,
        because Provalume's journal is append-only and transactional.
        """
        with contextlib.suppress(Exception):
            call()


def open_memory(
    project_root: Path,
    config: ProjectConfig,
    *,
    run_id: str,
    branch: str | None = None,
    base_commit: str | None = None,
) -> Memory | None:
    """Open memory for a run, or return ``None`` if it is unavailable.

    ``None`` is the normal, supported case: Provalume not installed, memory
    disabled in config, or a database that will not open. Callers treat ``None``
    as "no memory this run" and carry on.
    """
    if not config.memory.enabled:
        return None
    if not is_available():
        return None

    try:
        from provalume import Provalume
        from provalume.integrations.orkestra import OrkestraAdapter, OrkestraContext

        client = Provalume.open(
            project_root / ".orkestra" / "memory.db",
            project_id=config.project.name,
            root=project_root,
        )
        adapter = OrkestraAdapter(
            client,
            OrkestraContext(
                project_id=config.project.name,
                run_id=run_id,
                branch=branch,
                base_commit=base_commit,
            ),
        )
    except Exception:
        return None

    return Memory(adapter, client)

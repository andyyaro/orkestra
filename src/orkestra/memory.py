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
    from collections.abc import Sequence

    from orkestra.schemas.config import ProjectConfig

#: Why memory is not running. Set by :func:`is_available` for an import failure
#: and by :func:`open_memory` for a database that will not open — the second is
#: the one that used to be invisible, because a run with memory silently off
#: looked exactly like a run with it on.
#:
#: Read by the kernel, which emits one WARNING event per run when memory was
#: configured and did not start. `doctor` does not yet have a memory row; when
#: it grows one, this is what it reads.
_UNAVAILABLE_REASON = ""


def is_available() -> bool:
    """Whether Provalume is importable.

    A pure query: it reports, and records nothing. An earlier version assigned
    the module-level reason as a side effect of being asked, so one project's
    call could overwrite another's reason in a process running both.
    """
    try:
        import provalume  # noqa: F401
    except ImportError:
        return False
    return True


def unavailable_reason() -> str:
    """Why memory is off. Empty when it is available and last opened cleanly."""
    if not is_available():
        try:
            import provalume  # noqa: F401
        except ImportError as exc:
            return str(exc) or "provalume is not installed"
        return "provalume is not installed"
    # Importable, but the last open may still have failed. Reported rather than
    # cleared: "provalume imports fine" is not the same claim as "memory works".
    return _UNAVAILABLE_REASON


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
        return self.brief_context_detail(title=title, task_id=task_id, budget=budget)[0]

    def brief_context_detail(
        self, *, title: str, task_id: str, budget: int = 2000
    ) -> tuple[str, str]:
        """The digest, plus a reason when the *configuration* made it impossible.

        Two very different things produce an empty digest, and collapsing them
        was how a mis-set budget became invisible. A retrieval outage is expected
        and must stay quiet — memory fails open. A budget too small to hold
        Provalume's mandatory untrusted-data banner is a configuration error:
        *no* run at that setting can ever inject anything, so every other signal
        reporting healthy is a lie. The second returns a reason for the caller to
        surface once.

        ``safe_digest`` is deliberately not used here: it swallows
        ``BudgetExceeded`` along with everything else, which is precisely the
        distinction this method exists to keep. The fail-open guarantee is
        re-stated locally instead.
        """
        try:
            from provalume.errors import BudgetExceeded
            from provalume.integrations.generic import splice_digest

            try:
                digest = self._adapter.brief_digest(
                    query=title, char_budget=budget, task_id=task_id
                )
            except BudgetExceeded as exc:
                return "", str(exc)
            except Exception:
                # A memory outage is not a run outage, and not a config error.
                return "", ""
            if digest is None or not digest.items:
                return "", ""
            # Annotated rather than returned directly: Provalume is an optional
            # extra, so under a type-check without it installed everything
            # crossing this boundary is `Any`. Naming the type here is what keeps
            # the rest of the module strict.
            spliced: str = splice_digest("", digest)
            return spliced.strip(), ""
        except Exception:
            return "", ""

    def preflight_warning(self, *, commands: Sequence[str]) -> str:
        """A warning if any of these commands resembles a known failure, or ``""``.

        **Advisory only.** The caller appends it to the brief; nothing here can
        block a dispatch.

        Takes the *whole* command list, not its first entry. Verification records
        one result per command, so a task whose acceptance is
        ``["ruff check src", "pytest -q"]`` writes its gotcha against ``pytest
        -q`` — and a gate that only ever asked about ``ruff check src`` held the
        record and declined to surface it. The caller passes exactly the list
        ``_verify`` will run, so anything the gate can learn about is something
        it can also be asked about.

        Deliberately no ``subsystem``. Provalume matches it as a substring of a
        gotcha's text (``retrieval/preflight.py:_overlap``), so the obvious
        candidate — ``spec.kind.value`` — is worse than nothing: it is a task
        *kind*, not a component, and the kind ``test`` is a substring of
        ``pytest``, which made every recorded pytest gotcha match every test task
        at the "previously failed in test" tier. Orkestra has no component
        taxonomy to put here instead, and inventing one would be guessing, so the
        argument is omitted and matching rests on the command alone.
        """
        try:
            from provalume.integrations.orkestra import safe_preflight

            summary = ""
            top_confidence = -1.0
            shown: set[str] = set()
            other: set[str] = set()
            recorded = False
            asked: set[str] = set()
            for command in commands:
                if not command or command in asked:
                    continue
                asked.add(command)
                # At most one `warning.shown` for the whole set: the event means
                # "a warning was put in front of someone", and one brief carries
                # one warning however many commands were consulted. Provalume
                # only records on a match, so `record` stays live until the first
                # one lands.
                result = safe_preflight(self._adapter, command=command, record=not recorded)
                if result is None or not result.matched:
                    continue
                recorded = True
                ids = {str(match.memory_id) for match in result.matches}
                confidence = max((float(m.confidence) for m in result.matches), default=0.0)
                if confidence > top_confidence:
                    other |= shown
                    top_confidence = confidence
                    summary = str(result.summary)
                    shown = ids
                else:
                    other |= ids
            if not summary:
                return ""
            also = other - shown
            if also:
                count = len(also)
                summary += (
                    f"\n  ({count} further related record(s) matched another acceptance command.)"
                )
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
        fallback: bool = False,
    ) -> None:
        """Feed performance memory: which agent profile succeeds at what.

        ``fallback`` is threaded through rather than left at its default: an
        aggregate that cannot say how often an agent needed rescuing describes a
        different agent from the one that ran.
        """
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
                fallback=fallback,
            )
        )

    def record_decision(
        self,
        *,
        question: str,
        selected: str,
        rejected: tuple[str, ...] = (),
        note: str = "",
        task_id: str | None = None,
    ) -> None:
        """Record a resolved human decision gate.

        ``rejected`` is the reusable part: without it, nothing stops an agent
        re-proposing what a human already turned down. It is also the only input
        to the pre-action gate's rejected-alternative tier, which stays dead
        until something calls this.

        ``task_id`` scopes the decision to the task it unblocked; without it the
        record cannot be attributed to the work it was about.
        """
        self._safe(
            lambda: self._adapter.human_decision(
                question=question,
                selected=selected,
                rejected=rejected,
                rationale=note,
                authority="human",
                task_id=task_id,
            )
        )

    def record_run_started(self, *, run_id: str) -> None:
        """Open the run in the journal.

        Paired with :meth:`record_run_completed`. Without it every journal held a
        ``run.completed`` with no matching ``run.started``, so nothing downstream
        could tell a run that finished from a run that was never seen.
        """
        self._safe(lambda: self._adapter.run_started(run_id=run_id))

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

    A failure to open is recorded in :func:`unavailable_reason` so the caller can
    say so out loud. Swallowing it without a reason made a corrupt or locked
    database indistinguishable from a healthy run — recording nothing, injecting
    nothing, and reporting fine.
    """
    global _UNAVAILABLE_REASON
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
    except Exception as exc:
        _UNAVAILABLE_REASON = f"memory database would not open: {exc}"
        return None

    _UNAVAILABLE_REASON = ""
    return Memory(adapter, client)

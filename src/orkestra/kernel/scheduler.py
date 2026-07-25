"""The deterministic orchestration loop.

Pipeline per task: dispatch → agent attempt → deterministic commit →
verification gates → independent review → policy-checked integration.
Every transition is persisted; the loop can be killed at any point and
resumed (``resume()`` reconciles in-flight state first).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from orkestra.capabilities.ledger import record_task_outcome
from orkestra.capabilities.matrix import build_matrix
from orkestra.director import prompts
from orkestra.errors import PolicyViolation, VerificationError, WorkspaceError
from orkestra.ids import new_id
from orkestra.kernel.dag import TaskDag
from orkestra.kernel.retry import FALLBACK_IMMEDIATELY, BackoffPolicy, next_agent
from orkestra.schemas.agent import (
    AgentEvent,
    AgentResult,
    ErrorKind,
    EventKind,
    ResultStatus,
)
from orkestra.schemas.common import AttemptState, RunState, TaskKind, TaskState
from orkestra.schemas.decision import DecisionOption, HumanDecision
from orkestra.schemas.director import ReviewVerdict
from orkestra.schemas.task import TaskBrief
from orkestra.verify import VerificationOutcome, run_verification
from orkestra.workspace.worktrees import Workspace

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from orkestra.adapters.base import AgentAdapter
    from orkestra.adapters.runner import EventCallback
    from orkestra.kernel.quota import QuotaTracker
    from orkestra.policy import PolicyEngine
    from orkestra.schemas.config import ProjectConfig
    from orkestra.store import Store
    from orkestra.store.repo import TaskRow
    from orkestra.workspace import WorkspaceManager

MUTATING_KINDS = frozenset(
    {TaskKind.IMPLEMENT, TaskKind.TEST, TaskKind.DEBUG, TaskKind.DOCUMENT, TaskKind.INTEGRATE}
)


class Orchestrator:
    """Owns one project's runs. Single instance per process."""

    def __init__(
        self,
        project_root: Path,
        config: ProjectConfig,
        store: Store,
        adapters: dict[str, AgentAdapter],
        policy: PolicyEngine,
        workspaces: WorkspaceManager,
        *,
        on_event: Callable[[str, AgentEvent], None] | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self.root = project_root
        self.config = config
        self.store = store
        self.adapters = adapters
        self.policy = policy
        self.workspaces = workspaces
        self.backoff = backoff or BackoffPolicy()
        self._on_event = on_event
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._agent_versions: dict[str, str] = {}
        self.director_service: object | None = None  # DirectorService, wired by app
        self._quota: QuotaTracker | None = None  # created per execute()

    # ------------------------------------------------------------ events

    def emit(
        self,
        run_id: str,
        kind: EventKind,
        text: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = AgentEvent(kind=kind, text=text, data=data or {})
        self.store.append_event(run_id, event, task_id=task_id, attempt_id=attempt_id)
        if self._on_event:
            self._on_event(run_id, event)

    def _attempt_event_cb(self, run_id: str, task_id: str, attempt_id: str) -> EventCallback:
        def callback(event: AgentEvent) -> None:
            self.store.append_event(run_id, event, task_id=task_id, attempt_id=attempt_id)
            if self._on_event:
                self._on_event(run_id, event)

        return callback

    # ----------------------------------------------------------- control

    def request_pause(self, run_id: str) -> None:
        self.store.update_run_payload(run_id, control="pause")

    def request_cancel(self, run_id: str) -> None:
        self.store.update_run_payload(run_id, control="cancel")
        for flag in self._cancel_flags.values():
            flag.set()

    def _control(self, run_id: str) -> str:
        return str(self.store.get_run(run_id).payload.get("control") or "")

    # ------------------------------------------------------------- setup

    async def inventory_agents(self) -> dict[str, dict[str, str]]:
        """Detect adapters and record versions; returns summary per agent."""
        summary: dict[str, dict[str, str]] = {}
        for name, adapter in self.adapters.items():
            info = await adapter.detect()
            auth = await adapter.check_auth()
            self._agent_versions[name] = info.version
            summary[name] = {
                "adapter": adapter.adapter_id,
                "version": info.version,
                "available": str(info.available),
                "auth_ready": str(auth.ready),
                "detail": info.detail or auth.detail,
            }
        return summary

    def agent_version(self, agent: str) -> str:
        return self._agent_versions.get(agent, "")

    # ----------------------------------------------------------- executing

    async def execute(self, run_id: str) -> RunState:
        """Main loop: schedule ready tasks until terminal state."""
        self.store.get_run(run_id)  # existence check with a clear error
        tasks = {t.key: t for t in self.store.tasks_for_run(run_id)}
        if not tasks:
            self.store.set_run_state(run_id, RunState.FAILED)
            self.emit(
                run_id, EventKind.ERROR, "run has no tasks (preparation did not finish); plan again"
            )
            return RunState.FAILED
        self.store.set_run_state(run_id, RunState.RUNNING)
        from orkestra.kernel.quota import QuotaTracker

        self._quota = QuotaTracker(
            config=self.config,
            store=self.store,
            run_id=run_id,
            cooldown_base_s=self.backoff.rate_limit_base_s,
        )
        dag = TaskDag(deps=self.store.deps_for_run(run_id), all_keys=list(tasks.keys()))
        semaphore = asyncio.Semaphore(self.config.policy.max_concurrency)
        in_flight: dict[str, asyncio.Task[None]] = {}

        def states() -> dict[str, TaskState]:
            return {t.key: t.state for t in self.store.tasks_for_run(run_id)}

        try:
            return await self._execute_loop(run_id, dag, semaphore, in_flight, states)
        except asyncio.CancelledError:
            # Graceful in-process shutdown: cancel children so no pipeline
            # coroutine (or agent subprocess) outlives this call. A hard
            # process kill is covered by reconcile() on the next start.
            for aio_task in in_flight.values():
                aio_task.cancel()
            await asyncio.gather(*in_flight.values(), return_exceptions=True)
            raise

    async def _execute_loop(
        self,
        run_id: str,
        dag: TaskDag,
        semaphore: asyncio.Semaphore,
        in_flight: dict[str, asyncio.Task[None]],
        states: Callable[[], dict[str, TaskState]],
    ) -> RunState:
        while True:
            control = self._control(run_id)
            if control == "cancel":
                for aio_task in in_flight.values():
                    aio_task.cancel()
                await asyncio.gather(*in_flight.values(), return_exceptions=True)
                self._cancel_open_tasks(run_id)
                self.store.set_run_state(run_id, RunState.CANCELLED)
                self.emit(run_id, EventKind.WARNING, "run cancelled by operator")
                return RunState.CANCELLED
            if control == "pause" and not in_flight:
                self.store.set_run_state(run_id, RunState.PAUSED)
                self.emit(run_id, EventKind.WARNING, "run paused by operator")
                return RunState.PAUSED

            current = states()
            if dag.is_complete(current):
                self.store.set_run_state(run_id, RunState.COMPLETE)
                self.emit(run_id, EventKind.COMPLETED, "all tasks done")
                return RunState.COMPLETE

            if control != "pause":
                for key in dag.ready_keys(current):
                    if key in in_flight:
                        continue
                    task = self.store.tasks_for_run(run_id)
                    row = next(t for t in task if t.key == key)
                    self.store.set_task_state(
                        row.task_id,
                        TaskState.READY,
                        expected=(TaskState.PENDING, TaskState.READY),
                    )
                    in_flight[key] = asyncio.ensure_future(
                        self._run_task_guarded(run_id, row.task_id, semaphore)
                    )

            if not in_flight:
                current = states()
                if dag.is_stuck(current):
                    unresolved = self.store.decisions_for_run(run_id, unresolved_only=True)
                    if unresolved:
                        self.store.set_run_state(run_id, RunState.WAITING_HUMAN)
                        self.emit(
                            run_id,
                            EventKind.WARNING,
                            f"waiting on {len(unresolved)} human decision(s) — "
                            "see `orkestra decisions`",
                        )
                        return RunState.WAITING_HUMAN
                    self.store.set_run_state(run_id, RunState.FAILED)
                    self.emit(run_id, EventKind.ERROR, "run failed: no runnable tasks left")
                    return RunState.FAILED
                await asyncio.sleep(0.2)
                continue

            done, _ = await asyncio.wait(
                in_flight.values(), timeout=1.0, return_when=asyncio.FIRST_COMPLETED
            )
            finished = [k for k, t in in_flight.items() if t in done]
            for key in finished:
                exc = in_flight[key].exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    self.emit(run_id, EventKind.ERROR, f"task {key} crashed the pipeline: {exc}")
                    # A crashed pipeline coroutine must not strand its task in
                    # an active state (that would spin the loop forever) —
                    # block it behind a human decision instead.
                    crashed_task = next(
                        (t for t in self.store.tasks_for_run(run_id) if t.key == key), None
                    )
                    if crashed_task is not None and crashed_task.state not in (
                        TaskState.DONE,
                        TaskState.FAILED,
                        TaskState.CANCELLED,
                        TaskState.BLOCKED,
                    ):
                        self._block_task(run_id, crashed_task.task_id, f"pipeline crash: {exc}")
                del in_flight[key]

    def _cancel_open_tasks(self, run_id: str) -> None:
        for row in self.store.tasks_for_run(run_id):
            if row.state not in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED):
                self.store.set_task_state(row.task_id, TaskState.CANCELLED)
        for attempt in self.store.running_attempts(run_id):
            self.store.mark_interrupted(attempt.attempt_id)

    # ------------------------------------------------------------ resume

    async def reconcile(self, run_id: str) -> None:
        """Crash recovery: close dangling attempts, repair workspaces."""
        for attempt in self.store.running_attempts(run_id):
            self.store.mark_interrupted(attempt.attempt_id)
            self.emit(
                run_id,
                EventKind.WARNING,
                f"attempt {attempt.attempt_id} marked interrupted on resume",
                task_id=attempt.task_id,
            )
        recorded = [w.path for w in self.store.workspaces_for_run(run_id, state="active")]
        missing = await self.workspaces.reconcile(run_id, recorded)
        for workspace in self.store.workspaces_for_run(run_id, state="active"):
            if workspace.path in missing:
                self.store.set_workspace_state(workspace.workspace_id, "lost")
                continue
            # Stale-but-present worktree from an interrupted attempt: remove it
            # so the task can get a clean workspace (its branch is preserved
            # for forensics until the next attempt replaces it).
            from pathlib import Path as _Path

            from orkestra.workspace.worktrees import Workspace as _Workspace

            stale = _Workspace(
                path=_Path(workspace.path),
                branch=workspace.branch,
                base_commit=workspace.base_commit,
                task_id=workspace.task_id,
            )
            with contextlib.suppress(WorkspaceError):
                # On failure, leave for manual cleanup; creation uses unique paths.
                await self.workspaces.remove_workspace(stale, keep_branch=True)
            self.store.set_workspace_state(workspace.workspace_id, "removed")
        # Any task stranded mid-pipeline goes back to ready for a clean attempt.
        for row in self.store.tasks_for_run(run_id):
            if row.state in (
                TaskState.RUNNING,
                TaskState.VERIFYING,
                TaskState.REVIEWING,
                TaskState.INTEGRATING,
            ):
                self.store.set_task_state(row.task_id, TaskState.READY)
        payload_control = self._control(run_id)
        if payload_control == "pause":
            self.store.update_run_payload(run_id, control="")

    # ------------------------------------------------- task state machine

    async def _run_task_guarded(
        self, run_id: str, task_id: str, semaphore: asyncio.Semaphore
    ) -> None:
        async with semaphore:
            try:
                await self._run_task(run_id, task_id)
            except asyncio.CancelledError:
                raise
            except PolicyViolation as exc:
                self._block_task(run_id, task_id, f"policy violation: {exc}")
            except WorkspaceError as exc:
                self._block_task(run_id, task_id, f"workspace error: {exc}")
            except VerificationError as exc:
                # E.g. an acceptance command that isn't executable: a plan
                # defect the human should see, not an agent failure to retry.
                self._block_task(run_id, task_id, f"verification setup error: {exc}")

    def _block_task(self, run_id: str, task_id: str, reason: str) -> None:
        task = self.store.get_task(task_id)
        self.emit(run_id, EventKind.ERROR, f"task {task.key} blocked: {reason}", task_id=task_id)
        self._open_decision(
            run_id,
            task_id,
            question=f"Task {task.key!r} is blocked: {reason}. How should Orkestra proceed?",
            why=reason,
            options=[
                DecisionOption(key="retry", label="Reset the task and retry"),
                DecisionOption(
                    key="skip",
                    label="Skip this task (dependents will fail)",
                    consequences="downstream tasks cannot run",
                ),
                DecisionOption(key="abort", label="Fail the run"),
            ],
            recommendation="retry",
        )
        self.store.set_task_state(task_id, TaskState.BLOCKED)

    def _open_decision(
        self,
        run_id: str,
        task_id: str | None,
        question: str,
        why: str,
        options: list[DecisionOption],
        recommendation: str,
    ) -> str:
        from orkestra.kernel.explain import explain_block

        attempts = self.store.attempts_for_task(task_id) if task_id else []
        decision = HumanDecision(
            decision_id=new_id("dec"),
            run_id=run_id,
            task_id=task_id,
            question=question,
            why_blocked=why,
            options=options,
            recommendation=recommendation,
            plain=explain_block(why, attempts),
            unblocked_work="independent tasks continue; resume after deciding",
        )
        self.store.add_decision(decision)
        return decision.decision_id

    async def _run_task(self, run_id: str, task_id: str) -> None:
        task = self.store.get_task(task_id)
        assignment = task.assignment
        if assignment is None:
            self._block_task(run_id, task_id, "task has no assignment")
            return
        decision = self.policy.check_assignment(assignment)
        if not decision.allowed:
            self._block_task(run_id, task_id, "; ".join(decision.violations))
            return
        # Deterministic pre-flight: a gate that cannot even start would
        # fail identically after any amount of agent work. Catch it here
        # (and on every retry) so broken [verify] config never burns an
        # agent attempt — the fix is editing config, not re-running agents.
        from orkestra.verify.runner import gate_command_problem

        gate_problems = [
            f"{cmd!r}: {problem}"
            for cmd in self.config.verify.commands
            if (problem := gate_command_problem(cmd, strict=False))
        ]
        if gate_problems:
            self._block_task(
                run_id, task_id, "verification setup error: " + "; ".join(gate_problems)
            )
            return

        failed_agents: list[str] = []
        attempt_index = 0
        workspace: Workspace | None = None
        fix_context: str = ""
        # agent -> resumable session id, valid only for the current workspace
        # (all vendor CLIs scope sessions to the working directory).
        sessions: dict[str, str] = {}

        while True:
            # A pause request stops NEW attempts immediately — not just new
            # tasks. The current agent subprocess is never killed mid-flight;
            # the task simply goes back to READY for the resumed run.
            if self._control(run_id) == "pause":
                self.store.set_task_state(
                    task.task_id,
                    TaskState.READY,
                    expected=(TaskState.READY, TaskState.RUNNING),
                )
                return
            budget = self.policy.check_attempt_budget(task.attempt_count + attempt_index)
            quota = self._quota
            if quota is None:  # pragma: no cover - execute() always sets it
                msg = "quota tracker missing; _run_task outside execute()"
                raise RuntimeError(msg)
            agent, wait_s = quota.pick(failed_agents, assignment.primary, assignment.fallbacks)
            if not budget.allowed or agent is None:
                await self._exhausted(
                    run_id,
                    task,
                    failed_agents,
                    reason=(
                        "attempt budget exhausted"
                        if not budget.allowed
                        else "all candidate agents failed or exceeded token budgets"
                    ),
                )
                return
            if wait_s > 0:
                self.emit(
                    run_id,
                    EventKind.WARNING,
                    f"all eligible agents rate-limited; waiting {wait_s:.0f}s for {agent}",
                    task_id=task.task_id,
                )
                await asyncio.sleep(wait_s)

            self.store.set_task_state(
                task.task_id,
                TaskState.RUNNING,
                expected=(TaskState.READY, TaskState.RUNNING),
            )
            self.store.bump_task_counter(task.task_id, "attempt_count")
            attempt_index += 1

            if workspace is None:
                workspace = await self._make_workspace(run_id, task)
                sessions.clear()

            resume_id = sessions.get(agent) if self.config.policy.session_reuse else None
            result, attempt_id = await self._attempt(
                run_id, task, agent, workspace, fix_context, resume_session_id=resume_id
            )
            self.store.add_usage(run_id, agent, attempt_id, result.usage)
            if (
                result.ok
                and result.session is not None
                and result.session.cwd == str(workspace.path)
            ):
                sessions[agent] = result.session.session_id

            if not result.ok:
                self.store.finish_attempt(
                    attempt_id,
                    AttemptState.TIMEOUT
                    if result.error_kind is ErrorKind.TIMEOUT
                    else AttemptState.CANCELLED
                    if result.error_kind is ErrorKind.CANCELLED
                    else AttemptState.FAILED,
                    result,
                )
                record_task_outcome(
                    self.store,
                    run_id,
                    agent,
                    self.agent_version(agent),
                    task.task_id,
                    task.spec.kind.value,
                    succeeded=False,
                    detail=result.error_kind.value,
                )
                if result.error_kind is ErrorKind.CANCELLED:
                    self.store.set_task_state(task.task_id, TaskState.CANCELLED)
                    return
                if result.error_kind is ErrorKind.RATE_LIMIT:
                    delay = quota.note_rate_limit(agent)
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"agent {agent} rate-limited; cooling down {delay:.0f}s "
                        "(alternatives dispatch immediately)",
                        task_id=task.task_id,
                    )
                    self.store.set_task_state(
                        task.task_id,
                        TaskState.READY,
                        expected=(TaskState.RUNNING,),
                    )
                    continue
                if result.error_kind in FALLBACK_IMMEDIATELY:
                    failed_agents.append(agent)
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"agent {agent} unavailable ({result.error_kind.value}); trying fallback",
                        task_id=task.task_id,
                    )
                else:
                    delay = self.backoff.delay(attempt_index - 1, result.error_kind)
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"attempt by {agent} failed ({result.error_kind.value}); "
                        f"backing off {delay:.0f}s",
                        task_id=task.task_id,
                    )
                    await asyncio.sleep(delay)
                    failed_agents.append(agent)
                self.store.set_task_state(
                    task.task_id,
                    TaskState.READY,
                    expected=(TaskState.RUNNING,),
                )
                continue

            # Agent finished; deterministic pipeline takes over.
            quota.note_success(agent)
            self.store.finish_attempt(attempt_id, AttemptState.SUCCEEDED, result)
            mutating = task.spec.mutates_repo and task.spec.kind in MUTATING_KINDS
            commit = None
            if mutating:
                commit = await self.workspaces.commit_workspace(
                    workspace, f"orkestra[{agent}]: {task.spec.title}"
                )
                try:
                    await self.workspaces.validate_workspace_changes(workspace)
                except PolicyViolation as exc:
                    record_task_outcome(
                        self.store,
                        run_id,
                        agent,
                        self.agent_version(agent),
                        task.task_id,
                        task.spec.kind.value,
                        succeeded=False,
                        detail=f"policy: {exc}",
                    )
                    self._block_task(run_id, task_id, str(exc))
                    return

            self.store.set_task_state(
                task.task_id, TaskState.VERIFYING, expected=(TaskState.RUNNING,)
            )
            verify_outcome = await self._verify(run_id, task, workspace)
            if verify_outcome is not None and not verify_outcome.passed:
                record_task_outcome(
                    self.store,
                    run_id,
                    agent,
                    self.agent_version(agent),
                    task.task_id,
                    task.spec.kind.value,
                    succeeded=False,
                    detail="verification failed",
                )
                failed_agents_snapshot = list(failed_agents)
                failed_agents.append(agent)
                fix_context = (
                    "Deterministic verification failed. Output of the "
                    "failing command(s):\n\n"
                    + verify_outcome.failure_detail()
                    + "\n\nFix the code so these commands pass."
                )
                self.store.set_task_state(
                    task.task_id, TaskState.READY, expected=(TaskState.VERIFYING,)
                )
                # Verification failure keeps the same workspace so the next
                # attempt (same or fallback agent) repairs instead of restarts.
                if next_agent(failed_agents, assignment.primary, assignment.fallbacks) is None:
                    failed_agents = failed_agents_snapshot  # allow same-agent retry
                    fix_context += "\n(Repeated failure: previous fix attempt did not pass.)"
                continue

            if mutating and commit is not None and self.config.policy.require_review:
                self.store.set_task_state(
                    task.task_id, TaskState.REVIEWING, expected=(TaskState.VERIFYING,)
                )
                verdict = await self._review(run_id, task, workspace, agent)
                if verdict is None:
                    self._block_task(
                        run_id,
                        task_id,
                        "no independent reviewer could produce a verdict "
                        "(review is required by policy)",
                    )
                    return
                if not verdict.approve:
                    cycles = self.store.bump_task_counter(task.task_id, "review_cycles")
                    if not self.policy.check_review_budget(cycles).allowed:
                        await self._exhausted(
                            run_id, task, failed_agents, reason="review cycles exhausted"
                        )
                        return
                    fix_context = prompts.FIX.format(
                        title=task.spec.title,
                        description=task.spec.description[:4000],
                        findings="\n".join(f"- {f}" for f in verdict.findings),
                        required="\n".join(f"- {c}" for c in verdict.required_changes),
                    )
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"review requested changes (cycle {cycles})",
                        task_id=task.task_id,
                    )
                    self.store.set_task_state(
                        task.task_id, TaskState.READY, expected=(TaskState.REVIEWING,)
                    )
                    continue

            elif self.config.policy.require_review:
                # Honesty: never let "review required" look like it happened
                # when there was nothing to review.
                self.emit(
                    run_id,
                    EventKind.TEXT,
                    f"independent review skipped for {task.key}: task produced "
                    "no repository changes to review",
                    task_id=task.task_id,
                )

            if mutating and commit is not None:
                self.store.set_task_state(
                    task.task_id,
                    TaskState.INTEGRATING,
                    expected=(TaskState.REVIEWING, TaskState.VERIFYING),
                )
                merged = await self.workspaces.integrate(run_id, workspace, task.spec.title)
                if not merged:
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"merge conflict integrating {task.key}; recreating "
                        "workspace from updated integration branch",
                        task_id=task.task_id,
                    )
                    await self.workspaces.remove_workspace(workspace, keep_branch=True)
                    workspace = None
                    fix_context = ""
                    self.store.set_task_state(
                        task.task_id, TaskState.READY, expected=(TaskState.INTEGRATING,)
                    )
                    continue
                await self.workspaces.remove_workspace(workspace, keep_branch=True)
            else:
                # Non-mutating task: nothing to integrate. If the agent wrote
                # files anyway, say so — silently discarding work looks like
                # success and is indistinguishable from data loss.
                from orkestra.workspace.git import GitRepo

                _, dirty, _ = await GitRepo(workspace.path)._git(
                    "status", "--porcelain", check=False
                )
                discarded = [line[3:] for line in dirty.splitlines() if line.strip()]
                if discarded:
                    self.emit(
                        run_id,
                        EventKind.WARNING,
                        f"task {task.key} is a {task.spec.kind.value} task, so its "
                        f"file changes are not kept: {', '.join(discarded[:8])}"
                        + (" …" if len(discarded) > 8 else ""),
                        task_id=task.task_id,
                    )
                await self.workspaces.remove_workspace(workspace, keep_branch=False)

            record_task_outcome(
                self.store,
                run_id,
                agent,
                self.agent_version(agent),
                task.task_id,
                task.spec.kind.value,
                succeeded=True,
            )
            self.store.set_task_state(
                task.task_id,
                TaskState.DONE,
                expected=(TaskState.INTEGRATING, TaskState.VERIFYING),
            )
            self.emit(
                run_id,
                EventKind.COMPLETED,
                f"task {task.key} done (agent {agent})",
                task_id=task.task_id,
            )
            return

    # -------------------------------------------------------- sub-steps

    async def _make_workspace(self, run_id: str, task: TaskRow) -> Workspace:
        workspace = await self.workspaces.create_workspace(run_id, task.task_id)
        self.store.add_workspace(
            run_id,
            task.task_id,
            str(workspace.path),
            workspace.branch,
            workspace.base_commit,
        )
        return workspace

    async def _attempt(
        self,
        run_id: str,
        task: TaskRow,
        agent: str,
        workspace: Workspace,
        fix_context: str,
        *,
        resume_session_id: str | None = None,
    ) -> tuple[AgentResult, str]:
        adapter = self.adapters[agent]
        attempt_id = self.store.create_attempt(
            task.task_id, run_id, agent, "primary", str(workspace.path)
        )
        instructions = self._render_brief(task, fix_context)
        agent_config = self.config.agents[agent]
        brief = TaskBrief(
            task_id=task.task_id,
            run_id=run_id,
            title=task.spec.title,
            kind=task.spec.kind,
            instructions=instructions,
            cwd=str(workspace.path),
            timeout_s=min(agent_config.timeout_s, self.config.policy.task_timeout_s),
            resume_session_id=resume_session_id,
        )
        cancel_flag = asyncio.Event()
        self._cancel_flags[attempt_id] = cancel_flag
        try:
            result = await asyncio.wait_for(
                self._invoke(
                    adapter,
                    brief,
                    run_id,
                    task.task_id,
                    attempt_id,
                    cancel_flag,
                    agent_name=agent,
                ),
                timeout=brief.timeout_s + 120,
            )
        except TimeoutError:
            result = AgentResult(
                status=ResultStatus.ERROR,
                error_kind=ErrorKind.TIMEOUT,
                error_detail="hard kernel timeout",
            )
        finally:
            self._cancel_flags.pop(attempt_id, None)
        return result, attempt_id

    async def _invoke(
        self,
        adapter: AgentAdapter,
        brief: TaskBrief,
        run_id: str,
        task_id: str,
        attempt_id: str,
        cancel_flag: asyncio.Event,
        agent_name: str | None = None,
    ) -> AgentResult:
        from orkestra.adapters.docker import SANDBOXABLE_ADAPTERS, wrap_in_docker
        from orkestra.adapters.runner import run_invocation

        spec = adapter.build_invocation(brief)
        if self.config.policy.sandbox == "docker" and agent_name is not None:
            agent_config = self.config.agents.get(agent_name)
            if (
                agent_config is not None
                and agent_config.sandbox_image
                and adapter.adapter_id in SANDBOXABLE_ADAPTERS
            ):
                spec = wrap_in_docker(spec, agent_config.sandbox_image)
        base_cb = self._attempt_event_cb(run_id, task_id, attempt_id)

        def tagged(event: AgentEvent) -> None:
            """Stamp the acting agent so streamed output is attributable."""
            if agent_name and not event.data.get("agent"):
                event = event.model_copy(update={"data": {**event.data, "agent": agent_name}})
            base_cb(event)

        return await run_invocation(spec, adapter.make_parser(brief), tagged, cancel_flag)

    def _render_brief(self, task: TaskRow, fix_context: str) -> str:
        parts = [
            f"# Task: {task.spec.title}",
            "",
            task.spec.description,
            "",
            "## Rules",
            "- Work ONLY inside the current working directory (an isolated Git worktree).",
            "- Do not run `git commit`, `git push`, or modify Git configuration; "
            "the orchestrator commits your changes.",
            "- Do not touch `.github/workflows`, `.git`, or `.orkestra` paths.",
        ]
        gates = self._gate_commands("", task, quiet=True)
        if gates:
            parts += [
                "",
                "## Acceptance (the orchestrator will run these; they must pass)",
                *[f"- `{c}`" for c in gates],
            ]
        if fix_context:
            parts += ["", "## Follow-up context", fix_context]
        return "\n".join(parts)

    def _gate_commands(self, run_id: str, task: TaskRow, *, quiet: bool = False) -> list[str]:
        """The task's real verification gate: the user's [verify] commands
        always (authoritative), plus plan-derived acceptance entries that
        survive deterministic validation. Invalid plan entries are dropped
        with a warning — never exec'd, never allowed to block the run."""
        from orkestra.verify.runner import gate_command_problem

        commands = list(self.config.verify.commands)
        for entry in task.spec.acceptance or []:
            if entry in commands:
                continue
            problem = gate_command_problem(entry)
            if problem is None:
                commands.append(entry)
            elif not quiet:
                self.emit(
                    run_id,
                    EventKind.WARNING,
                    f"ignoring plan acceptance entry ({problem}): {entry!r}",
                    task_id=task.task_id,
                )
        return commands

    async def _verify(
        self, run_id: str, task: TaskRow, workspace: Workspace
    ) -> VerificationOutcome | None:
        """Run the gate; returns the outcome, or None when nothing to run."""
        commands = self._gate_commands(run_id, task)
        if not commands:
            return None
        outcome = await run_verification(
            commands, workspace.path, timeout_s=self.config.verify.timeout_s
        )
        text = f"verification {'passed' if outcome.passed else 'FAILED'}:\n{outcome.summary}"
        if not outcome.passed:
            text += "\n\nfailing output:\n" + outcome.failure_detail(2000)
        self.emit(
            run_id,
            EventKind.COMPLETED if outcome.passed else EventKind.ERROR,
            text,
            task_id=task.task_id,
        )
        return outcome

    async def _review(
        self, run_id: str, task: TaskRow, workspace: Workspace, implementer: str
    ) -> ReviewVerdict | None:
        assignment = task.assignment
        if assignment is None:  # pragma: no cover - guarded by caller
            return None
        from orkestra.adapters.jsonl import extract_json_object
        from orkestra.workspace.git import GitRepo

        wt = GitRepo(workspace.path)
        changed = await wt.changed_paths(workspace.base_commit)
        diffstat = await wt.diff_stat(workspace.base_commit)
        # Assigned reviewers first; if the implementer changed via fallback and
        # collides with every assigned reviewer, substitute any other enabled
        # agent — review independence is preserved, review coverage is kept.
        candidates = list(assignment.reviewers)
        candidates += [
            name for name in self.adapters if name not in candidates and name != implementer
        ]
        # Two bounded rounds: transient reviewer flakiness (empty responses,
        # malformed JSON) gets one more chance before escalating to a human.
        attempts_plan = [*candidates, *candidates]
        for reviewer in attempts_plan:
            pairing = self.policy.check_reviewer(implementer, reviewer)
            if not pairing.allowed:
                self.emit(
                    run_id,
                    EventKind.WARNING,
                    f"reviewer {reviewer} rejected by policy: " + "; ".join(pairing.violations),
                    task_id=task.task_id,
                )
                continue
            adapter = self.adapters[reviewer]
            attempt_id = self.store.create_attempt(
                task.task_id, run_id, reviewer, "reviewer", str(workspace.path)
            )
            brief = TaskBrief(
                task_id=task.task_id,
                run_id=run_id,
                title=f"review: {task.spec.title}",
                kind=TaskKind.REVIEW,
                instructions=prompts.REVIEW.format(
                    title=task.spec.title,
                    description=task.spec.description[:4000],
                    changed="\n".join(changed[:200]) or "(none)",
                    diffstat=diffstat[:2000] or "(empty)",
                ),
                cwd=str(workspace.path),
                timeout_s=self.config.policy.task_timeout_s,
                json_schema=ReviewVerdict.model_json_schema(),
            )
            cancel_flag = asyncio.Event()
            self._cancel_flags[attempt_id] = cancel_flag
            try:
                result = await self._invoke(
                    adapter,
                    brief,
                    run_id,
                    task.task_id,
                    attempt_id,
                    cancel_flag,
                    agent_name=reviewer,
                )
            finally:
                self._cancel_flags.pop(attempt_id, None)
            self.store.add_usage(run_id, reviewer, attempt_id, result.usage)
            if not result.ok:
                self.store.finish_attempt(attempt_id, AttemptState.FAILED, result)
                continue
            payload = result.structured or extract_json_object(result.final_text)
            if payload is None:
                self.store.finish_attempt(attempt_id, AttemptState.FAILED, result)
                continue
            try:
                verdict = ReviewVerdict.model_validate(payload)
            except Exception:
                self.store.finish_attempt(attempt_id, AttemptState.FAILED, result)
                continue
            self.store.finish_attempt(attempt_id, AttemptState.SUCCEEDED, result)
            record_task_outcome(
                self.store,
                run_id,
                reviewer,
                self.agent_version(reviewer),
                task.task_id,
                "review",
                succeeded=True,
            )
            self.emit(
                run_id,
                EventKind.COMPLETED,
                f"review by {reviewer}: "
                f"{'approved' if verdict.approve else 'changes requested'} "
                f"(severity {verdict.severity})",
                task_id=task.task_id,
                data={"findings": verdict.findings[:20]},
            )
            return verdict
        return None

    async def _exhausted(
        self,
        run_id: str,
        task: TaskRow,
        failed_agents: list[str],
        reason: str = "attempt budget exhausted",
    ) -> None:
        """Bounded escalation: ask the director, then a human."""
        observations = []
        for agent in self.adapters:
            observations.extend(self.store.observations_for(agent))
        matrix = build_matrix(observations)
        failures = json.dumps(
            [
                {
                    "agent": a.agent,
                    "state": a.state.value,
                    "error": a.result.error_detail[:200] if a.result else "",
                }
                for a in self.store.attempts_for_task(task.task_id)[-5:]
            ]
        )
        from orkestra.director import DirectorService

        advice = None
        if isinstance(self.director_service, DirectorService):
            advice = await self.director_service.reassign(
                task.spec.title, task.spec.kind.value, failures, matrix
            )
        if (
            advice is not None
            and not advice.escalate_to_human
            and advice.reassign_to
            and advice.reassign_to in self.adapters
            and advice.reassign_to not in failed_agents
        ):
            assignment = task.assignment
            if assignment is None:  # pragma: no cover
                return
            new_assignment = assignment.model_copy(
                update={
                    "primary": advice.reassign_to,
                    "reviewers": [r for r in assignment.reviewers if r != advice.reassign_to]
                    or [a for a in self.adapters if a != advice.reassign_to][:1],
                    "rationale": f"director reassignment: {advice.reason}",
                }
            )
            if self.policy.check_assignment(new_assignment).allowed:
                self.store.set_task_assignment(task.task_id, new_assignment)
                self.store.set_task_state(task.task_id, TaskState.READY)
                self.emit(
                    run_id,
                    EventKind.WARNING,
                    f"director reassigned {task.key} to {advice.reassign_to}",
                    task_id=task.task_id,
                )
                return
        self._open_decision(
            run_id,
            task.task_id,
            question=(
                f"Task {task.key!r} failed with all available agents ({reason}). "
                "How should Orkestra proceed?"
            ),
            why=f"{reason}; failed agents: {', '.join(failed_agents) or 'n/a'}",
            options=[
                DecisionOption(key="retry", label="Reset budgets and retry"),
                DecisionOption(
                    key="skip", label="Skip this task", consequences="dependent tasks cannot run"
                ),
                DecisionOption(key="abort", label="Fail the run"),
            ],
            recommendation="retry",
        )
        self.store.set_task_state(task.task_id, TaskState.BLOCKED)

    # ------------------------------------------------- decision handling

    def apply_decision(self, decision_id: str, option: str, note: str = "") -> str:
        """Resolve a human decision and apply its effect. Returns summary."""
        decision = self.store.resolve_decision(decision_id, option, note)
        if decision.task_id is None:
            return f"decision {decision_id} resolved: {option}"
        task = self.store.get_task(decision.task_id)
        if option == "retry":
            # Reset budgets by treating this as a fresh dispatch cycle.
            self.store.set_task_state(task.task_id, TaskState.READY, expected=(TaskState.BLOCKED,))
            with self.store.db.tx() as conn:
                conn.execute(
                    "UPDATE tasks SET attempt_count = 0, review_cycles = 0 WHERE task_id = ?",
                    (task.task_id,),
                )
            return f"task {task.key} reset and ready; run `orkestra resume`"
        if option == "skip":
            self.store.set_task_state(task.task_id, TaskState.FAILED, expected=(TaskState.BLOCKED,))
            return f"task {task.key} marked failed (skipped)"
        if option == "abort":
            self.store.set_task_state(task.task_id, TaskState.FAILED, expected=(TaskState.BLOCKED,))
            self.store.set_run_state(decision.run_id, RunState.FAILED)
            return "run marked failed"
        return f"decision {decision_id} resolved: {option}"

"""`orkestra demo` - the zero-risk, zero-quota full-lifecycle showcase.

Creates a throwaway project with scripted fake agents and runs the real
kernel through everything Orkestra does on real projects: planning,
parallel isolated tasks, a deterministic verification gate, an
independent review that REJECTS once and forces a repair, integration,
and the final report. No agent CLIs, no credentials, no tokens spent.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from orkestra.schemas.agent import AgentEvent, EventKind

if TYPE_CHECKING:
    from orkestra.app import App

console = Console()

_CONFIG = """
version = 1

[project]
name = "orkestra-demo"

[agents.ada]
adapter = "fake"

[agents.grace]
adapter = "fake"

[director]
agent = "ada"

[policy]
max_concurrency = 2

[probes]
mode = "off"
"""

_SPEC = "# Demo\nScripted showcase project (fake agents, no quota).\n"


def _narrate(text: str) -> None:
    console.print(f"\n[bold cyan]▸ {text}[/bold cyan]")


async def _run_demo(root: Path) -> bool:
    from orkestra.app import build_app
    from orkestra.schemas.common import RunState, TaskKind
    from orkestra.schemas.task import Assignment, TaskSpec
    from orkestra.workspace.git import GitRepo

    repo = GitRepo(root)
    await repo.init()
    (root / ".gitignore").write_text(".orkestra/\n")
    (root / "SPEC.md").write_text(_SPEC)
    (root / ".orkestra").mkdir()
    (root / ".orkestra" / "config.toml").write_text(_CONFIG)
    await repo.add_all_and_commit("demo project")

    application: App = build_app(root, offline=True)
    try:
        _narrate(
            "Two agents ('ada' and 'grace') will collaborate. They are "
            "scripted fakes - every mechanism below is the real kernel."
        )
        run_id = application.store.create_run("orkestra-demo")
        application.store.update_run_payload(
            run_id,
            agents={
                name: {"available": "True", "version": "demo", "detail": "scripted fake agent"}
                for name in ("ada", "grace")
            },
        )
        base, integration = await application.workspaces.start_run(run_id)
        application.store.set_run_git(run_id, base, integration)

        _narrate(
            "The plan: two independent tasks run in PARALLEL, each in its "
            "own isolated Git worktree, then a third task builds on both."
        )
        tasks = [
            TaskSpec(
                key="feature-a",
                title="Implement feature A",
                kind=TaskKind.IMPLEMENT,
                description=(
                    "FAKE:reject_once:demo reviewer wants a docstring\n"
                    "FAKE:write:feature_a.py:def feature_a():\\n    return 'A'"
                ),
                acceptance=["test -f feature_a.py"],
            ),
            TaskSpec(
                key="feature-b",
                title="Implement feature B",
                kind=TaskKind.IMPLEMENT,
                description="FAKE:write:feature_b.py:def feature_b():\\n    return 'B'",
                acceptance=["test -f feature_b.py"],
            ),
            TaskSpec(
                key="docs",
                title="Document both features",
                kind=TaskKind.DOCUMENT,
                description="FAKE:write:USAGE.md:Features A and B. See tests.",
                depends_on=["feature-a", "feature-b"],
            ),
        ]
        assignments = [
            Assignment(primary="ada", reviewers=["grace"]),
            Assignment(primary="grace", reviewers=["ada"]),
            Assignment(primary="ada", reviewers=["grace"]),
        ]
        for task_spec, assignment in zip(tasks, assignments, strict=True):
            application.store.add_task(run_id, task_spec, assignment)

        _narrate(
            "Watch for: a deterministic gate check after every task, and "
            "grace REJECTING ada's first attempt at feature A - ada must "
            "repair it before anything is integrated. Running now…"
        )

        def print_event(_run: str, event: AgentEvent) -> None:
            text = event.text.strip().replace("\n", " ")[:160]
            if not text:
                return
            styles = {
                EventKind.ERROR: "red",
                EventKind.WARNING: "yellow",
                EventKind.COMPLETED: "green",
            }
            style = styles.get(event.kind)
            if style:
                console.print(f"  [{style}]{event.kind.value:>9}[/{style}] {text}")

        application.orchestrator._on_event = print_event
        state = await application.orchestrator.execute(run_id)

        if state is not RunState.COMPLETE:
            from rich.markup import escape

            console.print(f"[red]demo ended in state {state.value} (unexpected)[/red]")
            # This path must explain itself: the one CI flake we ever saw
            # here (py3.12/macOS, 2026-07-26) exited 1 with no diagnosis,
            # and one sample with no evidence is undebuggable. Dump what
            # the kernel knows before giving up.
            for row in application.store.tasks_for_run(run_id):
                console.print(f"  task {escape(row.key)}: {row.state.value}")
            for decision in application.store.decisions_for_run(run_id, unresolved_only=True):
                console.print(f"  open decision: {escape(decision.question)}")
            events = application.store.events_for_run(run_id, limit=500)
            problems = [e for e in events if e["kind"] in ("error", "warning")]
            for event in problems[-10:]:
                console.print(f"  {event['kind']}: {escape(str(event['text']))[:300]}")
            return False

        _narrate("Done. What just happened:")
        task_rows = application.store.tasks_for_run(run_id)
        review_cycles = sum(t.review_cycles for t in task_rows)
        console.print(
            f"  • {len(task_rows)} tasks planned, isolated, verified, "
            f"cross-reviewed, and integrated\n"
            f"  • {review_cycles} review rejection triggered a repair loop "
            "(bounded - it can never spin forever)\n"
            "  • every result was integrated commit-by-commit into a holding "
            "area; the demo's own 'main' was never touched"
        )
        _, files, _ = await repo._git("ls-tree", "-r", "--name-only", integration)
        built = [
            f
            for f in files.splitlines()
            if f not in (".gitignore", "SPEC.md") and not f.startswith(".fake-")
        ]
        console.print(f"  • files built: {', '.join(sorted(built))}")
        _narrate(
            "On a real project the agents are Claude Code / Codex / "
            "Antigravity and the gates are YOUR test commands. "
            "Next: `orkestra start` in a repo of yours."
        )
        return True
    finally:
        application.close()


def run_demo(path: Path | None) -> bool:
    """Entry point used by the CLI command. Returns success."""
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
        target = path
        console.print(f"[dim]demo project: {target}[/dim]")
        return asyncio.run(_run_demo(target))
    with tempfile.TemporaryDirectory(prefix="orkestra-demo-") as tmp:
        console.print(f"[dim]demo project (temporary): {tmp}[/dim]")
        return asyncio.run(_run_demo(Path(tmp)))

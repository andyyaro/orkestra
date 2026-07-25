"""Orkestra CLI — the complete operator surface."""

from __future__ import annotations

import asyncio
import shutil
import subprocess  # nosec B404 - argv-only execution, no shell
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

import orkestra
from orkestra.app import CONFIG_RELPATH, App, build_app
from orkestra.errors import ConfigError, OrkestraError
from orkestra.schemas.agent import AgentEvent, EventKind
from orkestra.schemas.common import RunState

app = typer.Typer(
    name="orkestra",
    help="Local-first orchestration runtime for multiple coding agents.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
agents_app = typer.Typer(help="Inspect and probe configured agents.")
app.add_typer(agents_app, name="agents")

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"orkestra {orkestra.__version__}")
        raise typer.Exit


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """Coordinate many agents. Deliver one verified result."""


def _fail(message: str) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _load_app(offline: bool = False) -> App:
    try:
        return build_app(offline=offline)
    except ConfigError as exc:
        _fail(str(exc))
        raise AssertionError from None  # unreachable


def _pick_run(application: App, run_id: str | None) -> str:
    if run_id:
        return run_id
    latest = application.store.latest_run()
    if latest is None:
        _fail("no runs found — start one with `orkestra run`")
        raise AssertionError from None  # unreachable
    return latest.run_id


def _read_spec(application: App, spec: Path | None) -> str:
    path = spec or (application.root / application.config.project.spec_file)
    if not path.is_file():
        _fail(f"specification file not found: {path} — create it or pass --spec")
    text = path.read_text(encoding="utf-8")
    from orkestra.cli.detect import spec_nudges

    for nudge in spec_nudges(text):
        console.print(f"[yellow]spec hint:[/yellow] {nudge}")
    return text


def _progress_callback(application: App) -> Callable[[str, AgentEvent], None]:
    """Event printer plus a one-line progress/cost summary per finished task."""

    def callback(run_id: str, event: AgentEvent) -> None:
        _print_event(run_id, event)
        if event.kind is EventKind.COMPLETED and event.text.startswith("task "):
            tasks = application.store.tasks_for_run(run_id)
            done = sum(1 for t in tasks if t.state.value == "done")
            usage = application.store.usage_summary(run_id)
            tokens = sum((row["input_tokens"] or 0) + (row["output_tokens"] or 0) for row in usage)
            cost = sum(row["total_cost_usd"] or 0 for row in usage)
            cost_text = f" · ${cost:.2f}" if cost else ""
            console.print(
                f"[bold]  ▸ progress: {done}/{len(tasks)} tasks · "
                f"{tokens / 1000:.0f}k tokens{cost_text}[/bold]"
            )

    return callback


def _print_event(_run_id: str, event: AgentEvent) -> None:
    styles = {
        EventKind.ERROR: "red",
        EventKind.WARNING: "yellow",
        EventKind.COMPLETED: "green",
        EventKind.STARTED: "cyan",
    }
    style = styles.get(event.kind)
    text = event.text.strip().replace("\n", " ")[:220]
    if not text:
        return
    label = event.kind.value
    if style:
        console.print(f"[{style}]{label:>9}[/{style}] {text}", highlight=False)
    elif event.kind in (EventKind.TEXT, EventKind.TOOL):
        console.print(f"[dim]{label:>9} {text}[/dim]", highlight=False)


# ------------------------------------------------------------------ init


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Project directory.")] = Path(),
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="Never prompt; accept defaults.")
    ] = False,
) -> None:
    """Initialize an Orkestra project (config, spec template, Git safety)."""
    from orkestra.cli.template import SPEC_TEMPLATE, render_config
    from orkestra.workspace.git import GitRepo

    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_RELPATH
    if config_path.exists():
        _fail(f"{config_path} already exists — refusing to overwrite")

    async def _setup() -> None:
        repo = GitRepo(root)
        if not await repo.is_repo():
            await repo.init()
            console.print("initialized Git repository")
        gitignore = root / ".gitignore"
        marker = ".orkestra/"
        existing = gitignore.read_text() if gitignore.exists() else ""
        if marker not in existing.split("\n"):
            gitignore.write_text(
                existing
                + ("\n" if existing and not existing.endswith("\n") else "")
                + "# Orkestra local state (never commit)\n.orkestra/\n"
            )
        detected = {
            "claude": shutil.which("claude") is not None,
            "codex": shutil.which("codex") is not None,
            "antigravity": shutil.which("agy") is not None,
            "gemini": shutil.which("gemini") is not None,
        }
        from orkestra.cli.detect import detect_verify_commands

        verify_commands = detect_verify_commands(root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            render_config(
                root.name.lower().replace(" ", "-") or "project",
                detected,
                verify_commands=verify_commands,
            )
        )
        if verify_commands:
            console.print(
                "detected test culture — pre-filled [verify] commands: "
                + ", ".join(f"`{c}`" for c in verify_commands)
            )
        else:
            console.print(
                "[yellow]no test commands detected[/yellow] — add your own to "
                "[verify] in .orkestra/config.toml; they are the safety net "
                "agents cannot talk past"
            )
        spec_path = root / "SPEC.md"
        if not spec_path.exists():
            spec_path.write_text(SPEC_TEMPLATE.format(name=root.name))
            console.print(f"created {spec_path.name} — describe your project there")
        if not await repo.has_commits():
            await repo.add_all_and_commit("orkestra init")
            console.print("created initial commit")
        console.print(f"[green]✓[/green] project initialized at {root}")
        found = [name for name, ok in detected.items() if ok]
        console.print(
            f"detected agent CLIs: {', '.join(found) or 'none'} — "
            "run `orkestra doctor` to verify readiness"
        )

    asyncio.run(_setup())


@app.command()
def demo(
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Keep the demo project here instead of a temp dir."),
    ] = None,
) -> None:
    """See the full lifecycle in under a minute — free, no agent CLIs needed."""
    from orkestra.cli.demo import run_demo

    if not run_demo(path):
        raise typer.Exit(code=1)


# ---------------------------------------------------------------- doctor


@app.command()
def doctor() -> None:
    """Check Git, configuration, agents, and platform readiness."""
    application = _load_app()

    async def _run() -> int:
        problems = 0
        table = Table(title="orkestra doctor", show_lines=False)
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail", overflow="fold", max_width=70)

        git_path = shutil.which("git")
        table.add_row(
            "git",
            "[green]ok[/green]" if git_path else "[red]missing[/red]",
            git_path or "install Git",
        )
        problems += 0 if git_path else 1
        try:
            git_version = subprocess.run(
                [git_path or "/usr/bin/git", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
        except Exception:
            git_version = ""
        worktree_ok = bool(git_version)
        table.add_row(
            "git worktrees",
            "[green]ok[/green]" if worktree_ok else "[red]unknown[/red]",
            git_version,
        )

        try:
            await application.workspaces.validate_repository(allow_dirty=True)
            table.add_row("repository", "[green]ok[/green]", str(application.root))
        except OrkestraError as exc:
            problems += 1
            table.add_row("repository", "[red]problem[/red]", str(exc))

        table.add_row(
            "configuration",
            "[green]ok[/green]",
            f"{len(application.config.enabled_agents)} agents enabled, "
            f"director={application.config.director.agent}",
        )
        table.add_row(
            "state database",
            "[green]ok[/green]",
            str(application.root / ".orkestra" / "orkestra.db"),
        )

        ready_agents = 0
        for name, adapter in application.adapters.items():
            info = await adapter.detect()
            auth = await adapter.check_auth()
            if info.available and auth.ready:
                ready_agents += 1
                status = "[green]ready[/green]"
                detail = f"{adapter.adapter_id} {info.version}"
                if info.detail:
                    detail += f" — {info.detail}"
            elif info.available:
                status = "[yellow]auth needed[/yellow]"
                detail = auth.detail
            else:
                status = "[red]unavailable[/red]"
                detail = info.detail
            table.add_row(f"agent: {name}", status, detail)
        if ready_agents < 2:
            problems += 1
            table.add_row(
                "agents overall",
                "[red]insufficient[/red]",
                f"only {ready_agents} agent(s) ready; Orkestra needs at least 2 — "
                "sign in to the vendor CLIs (e.g. run `claude`, `codex login`, `agy`)",
            )
        else:
            table.add_row("agents overall", "[green]ok[/green]", f"{ready_agents} agents ready")

        docker = shutil.which("docker")
        if application.config.policy.sandbox == "docker":
            daemon_ok = False
            if docker:
                probe = subprocess.run(
                    [docker, "info"], capture_output=True, timeout=20, check=False
                )
                daemon_ok = probe.returncode == 0
            if not daemon_ok:
                problems += 1
            table.add_row(
                "docker (required: sandbox enabled)",
                "[green]ok[/green]" if daemon_ok else "[red]daemon unavailable[/red]",
                'policy.sandbox = "docker" needs a running Docker daemon',
            )
        else:
            table.add_row(
                "docker (optional)",
                "[green]present[/green]" if docker else "[yellow]absent[/yellow]",
                "used only for the opt-in docker sandbox",
            )
        console.print(table)
        if problems:
            err_console.print(f"[red]{problems} problem(s) found[/red]")
        return problems

    problems = asyncio.run(_run())
    application.close()
    raise typer.Exit(code=1 if problems else 0)


# ---------------------------------------------------------------- agents


@agents_app.command("list")
def agents_list() -> None:
    """Show configured agents, versions, and auth readiness."""
    application = _load_app()

    async def _run() -> None:
        table = Table(title="agents")
        for column in ("Name", "Adapter", "Version", "Available", "Auth", "Notes"):
            table.add_column(column, overflow="fold", max_width=50)
        for name, adapter in application.adapters.items():
            info = await adapter.detect()
            auth = await adapter.check_auth()
            table.add_row(
                name,
                adapter.adapter_id,
                info.version,
                "yes" if info.available else "no",
                "ready" if auth.ready else "not ready",
                info.detail or auth.detail,
            )
        console.print(table)

    asyncio.run(_run())
    application.close()


@agents_app.command("probe")
def agents_probe(
    live: Annotated[
        bool, typer.Option("--live", help="Force live probes even if cached results exist.")
    ] = False,
) -> None:
    """Measure agent capabilities with bounded probes and show the matrix."""
    application = _load_app()

    async def _run() -> None:
        from orkestra.capabilities import run_probes
        from orkestra.capabilities.matrix import build_matrix

        adapters = {}
        versions = {}
        for name, adapter in application.adapters.items():
            info = await adapter.detect()
            auth = await adapter.check_auth()
            if info.available and auth.ready:
                adapters[name] = adapter
                versions[name] = info.version
        mode = "live" if live else application.config.probes.mode
        if mode == "off":
            console.print('probes are disabled (probes.mode = "off")')
            return
        console.print(f"running probes (mode={mode}, budget={application.config.probes.budget})...")
        await run_probes(
            adapters,
            versions,
            application.store,
            application.root,
            mode=mode,
            budget=application.config.probes.budget,
            timeout_s=application.config.probes.timeout_s,
        )
        observations = []
        for name in application.adapters:
            observations.extend(application.store.observations_for(name))
        matrix = build_matrix(observations)
        table = Table(title="capability matrix (evidence-based)")
        table.add_column("Agent")
        table.add_column("Capability")
        table.add_column("Score")
        table.add_column("Confidence")
        table.add_column("Evidence")
        for agent_name, capabilities in sorted(matrix.scores.items()):
            for capability, score in sorted(capabilities.items()):
                table.add_row(
                    agent_name,
                    capability,
                    f"{score.score:.2f}",
                    f"{score.confidence:.2f}",
                    str(len(score.evidence)),
                )
        console.print(table)

    asyncio.run(_run())
    application.close()


# ----------------------------------------------------------- analyze/plan


@app.command()
def analyze(
    spec: Annotated[Path | None, typer.Option(help="Specification file.")] = None,
    offline: Annotated[bool, typer.Option("--offline")] = False,
) -> None:
    """Run director analysis of the specification (no run is created)."""
    application = _load_app(offline=offline)
    spec_text = _read_spec(application, spec)

    async def _run() -> None:
        summary = await application.orchestrator.inventory_agents()
        agents_summary = "\n".join(
            f"- {name}: {s['adapter']} {s['version']}" for name, s in summary.items()
        )
        analysis = await application.director.analyze(spec_text, agents_summary)
        console.print(f"[bold]Summary:[/bold] {analysis.summary}")
        if analysis.assumptions:
            console.print("[bold]Assumptions:[/bold]")
            for assumption in analysis.assumptions:
                console.print(f"  - {assumption}")
        if analysis.risks:
            console.print("[bold]Risks:[/bold]")
            for risk in analysis.risks:
                console.print(f"  - {risk}")
        if analysis.capability_demands:
            console.print("[bold]Capability demands:[/bold]")
            for capability, weight in sorted(
                analysis.capability_demands.items(), key=lambda kv: -kv[1]
            ):
                console.print(f"  - {capability}: {weight:.2f}")

    asyncio.run(_run())
    application.close()


@app.command()
def plan(
    spec: Annotated[Path | None, typer.Option(help="Specification file.")] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Heuristic planning, no LLM calls.")
    ] = False,
) -> None:
    """Prepare a run: analyze, probe, plan, challenge — without executing."""
    application = _load_app(offline=offline)
    spec_text = _read_spec(application, spec)

    async def _run() -> str:
        from orkestra.kernel.prepare import prepare_run

        application.orchestrator._on_event = _print_event
        return await prepare_run(application.orchestrator, application.director, spec_text)

    try:
        run_id = asyncio.run(_run())
    except OrkestraError as exc:
        application.close()
        _fail(str(exc))
        return
    _show_status(application, run_id)
    console.print(
        f"\n[green]plan ready[/green] — run it with: [bold]orkestra run[/bold] (run id {run_id})"
    )
    application.close()


# -------------------------------------------------------------------- run


@app.command()
def run(
    spec: Annotated[Path | None, typer.Option(help="Specification file.")] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Heuristic planning, no director LLM calls.")
    ] = False,
    watch: Annotated[
        bool, typer.Option("--watch", help="Attach the live TUI while the run executes.")
    ] = False,
) -> None:
    """Plan (if needed) and execute until done, blocked, or cancelled."""
    application = _load_app(offline=offline)

    async def _prepare() -> str:
        from orkestra.kernel.prepare import prepare_run

        latest = application.store.latest_run()
        if (
            latest is not None
            and latest.state is RunState.PLANNING
            and application.store.tasks_for_run(latest.run_id)
        ):
            console.print(f"executing prepared run {latest.run_id}")
            return latest.run_id
        spec_text = _read_spec(application, spec)
        return await prepare_run(application.orchestrator, application.director, spec_text)

    async def _run() -> RunState:
        application.orchestrator._on_event = _progress_callback(application)
        run_id = await _prepare()
        return await application.orchestrator.execute(run_id)

    if watch:
        import sys

        if not sys.stdout.isatty():
            application.close()
            _fail("--watch needs an interactive terminal (the TUI cannot render here)")
            return
        try:
            from orkestra.cli.watch import WatchApp  # noqa: F401
        except ModuleNotFoundError:
            application.close()
            _fail("--watch needs Textual — install with: uv tool install 'orkestra-runtime[tui]'")
            return
        application.orchestrator._on_event = _progress_callback(application)
        try:
            run_id = asyncio.run(_prepare())
        except OrkestraError as exc:
            application.close()
            _fail(str(exc))
            return
        state = _execute_with_watch(application.root, run_id, offline=offline)
        _show_status(application, run_id)
        application.close()
        if state is RunState.WAITING_HUMAN:
            raise typer.Exit(code=2)
        raise typer.Exit(code=1 if state is RunState.FAILED else 0)

    try:
        state = asyncio.run(_run())
    except OrkestraError as exc:
        application.close()
        _fail(str(exc))
        return
    latest = application.store.latest_run()
    if latest is None:  # pragma: no cover - run() just created one
        raise RuntimeError("no run recorded after execution")
    _show_status(application, latest.run_id)
    application.close()
    if state is RunState.COMPLETE:
        console.print(
            f"\n[green]run complete[/green] — verified results are on branch "
            f"[bold]{latest.integration_branch}[/bold]; merge when satisfied."
        )
    elif state is RunState.WAITING_HUMAN:
        console.print(
            "\n[yellow]run is waiting on your decision[/yellow] — "
            "see `orkestra decisions`, then `orkestra resume`"
        )
        raise typer.Exit(code=2)
    else:
        raise typer.Exit(code=1 if state is RunState.FAILED else 0)


def _execute_with_watch(root: Path, run_id: str, *, offline: bool) -> RunState:
    """Run the kernel in a worker thread while the TUI owns the terminal.

    The worker builds its own App (SQLite connections are per-thread); the
    two sides coordinate through the shared WAL database exactly like two
    separate processes would.
    """
    import threading

    from orkestra.cli.watch import WatchApp

    result: dict[str, RunState] = {}

    def worker() -> None:
        worker_app = build_app(root, offline=offline)
        try:
            result["state"] = asyncio.run(worker_app.orchestrator.execute(run_id))
        finally:
            worker_app.close()

    thread = threading.Thread(target=worker, name="orkestra-execute", daemon=True)
    thread.start()
    watch_application = build_app(root, offline=offline)
    try:
        WatchApp(watch_application, run_id).run()
        if thread.is_alive():
            console.print(
                "[yellow]TUI closed while the run is still executing — "
                "waiting for it to finish (Ctrl-C cancels the run)[/yellow]"
            )
        try:
            thread.join()
        except KeyboardInterrupt:
            console.print("[red]cancelling run…[/red]")
            watch_application.orchestrator.request_cancel(run_id)
            thread.join(timeout=120)
        return result.get("state", watch_application.store.get_run(run_id).state)
    finally:
        watch_application.close()


# ------------------------------------------------------------ status/logs


def _show_status(application: App, run_id: str) -> None:
    run = application.store.get_run(run_id)
    console.print(f"\n[bold]run {run.run_id}[/bold] — state: {run.state.value}")
    table = Table(show_lines=False)
    for column in ("Task", "Kind", "State", "Primary", "Reviewers", "Attempts"):
        table.add_column(column)
    for task in application.store.tasks_for_run(run_id):
        assignment = task.assignment
        state_style = {
            "done": "green",
            "failed": "red",
            "blocked": "yellow",
            "cancelled": "dim",
        }.get(task.state.value, "")
        state_text = (
            f"[{state_style}]{task.state.value}[/{state_style}]"
            if state_style
            else task.state.value
        )
        table.add_row(
            task.key,
            task.spec.kind.value,
            state_text,
            assignment.primary if assignment else "—",
            ", ".join(assignment.reviewers) if assignment else "—",
            str(task.attempt_count),
        )
    console.print(table)


@app.command()
def status(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the current run's task graph state."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    if as_json:
        from orkestra.report.final import build_report, render_json

        console.print_json(render_json(build_report(application.store, resolved)))
    else:
        _show_status(application, resolved)
        unresolved = application.store.decisions_for_run(resolved, unresolved_only=True)
        if unresolved:
            console.print(
                f"[yellow]{len(unresolved)} open decision(s)[/yellow] — `orkestra decisions`"
            )
    application.close()


@app.command()
def logs(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    task: Annotated[str | None, typer.Option("--task", help="Filter by task key.")] = None,
    limit: Annotated[int, typer.Option("--limit")] = 100,
) -> None:
    """Show recent run events (redacted at write time)."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    task_id = None
    if task:
        matching = [t for t in application.store.tasks_for_run(resolved) if t.key == task]
        if not matching:
            _fail(f"no task with key {task!r} in run {resolved}")
        task_id = matching[0].task_id
    for event in application.store.events_for_run(resolved, limit=limit, task_id=task_id):
        console.print(
            f"[dim]{event['ts'][:19]}[/dim] {event['kind']:>9} {event['text'][:200]}",
            highlight=False,
        )
    application.close()


# -------------------------------------------------------------- decisions


@app.command()
def decisions(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    show_all: Annotated[bool, typer.Option("--all", help="Include resolved.")] = False,
) -> None:
    """List human decisions awaiting your input."""
    application = _load_app()
    resolved_run = _pick_run(application, run_id)
    entries = application.store.decisions_for_run(resolved_run, unresolved_only=not show_all)
    if not entries:
        console.print("no open decisions")
    for decision in entries:
        console.print(
            f"\n[bold]{decision.decision_id}[/bold]"
            + (" [green](resolved)[/green]" if decision.resolved else "")
        )
        console.print(f"  question: {decision.question}")
        console.print(f"  why: {decision.why_blocked}")
        if decision.plain:
            console.print(f"  [cyan]what this means:[/cyan] {decision.plain}")
        for option in decision.options:
            marker = "→" if option.key == decision.recommendation else " "
            console.print(
                f"  {marker} --option {option.key}: {option.label}"
                + (f" ({option.consequences})" if option.consequences else "")
            )
        if decision.resolved:
            console.print(f"  chosen: {decision.chosen_option}")
        else:
            console.print(f"  resolve with: orkestra approve {decision.decision_id} --option <key>")
    application.close()


@app.command()
def approve(
    decision_id: Annotated[str | None, typer.Argument()] = None,
    option: Annotated[str | None, typer.Option("--option")] = None,
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    """Resolve a pending decision (no arguments needed when only one is open)."""
    application = _load_app()
    if decision_id is None:
        run = application.store.latest_run()
        open_decisions = (
            application.store.decisions_for_run(run.run_id, unresolved_only=True) if run else []
        )
        if not open_decisions:
            application.close()
            _fail("no open decisions")
            return
        if len(open_decisions) > 1:
            application.close()
            _fail(
                f"{len(open_decisions)} decisions are open — run "
                "`orkestra decisions` and pass the id you want to resolve"
            )
            return
        decision_id = open_decisions[0].decision_id
    if option is None:
        try:
            pending = application.store.get_decision(decision_id)
        except OrkestraError as exc:
            application.close()
            _fail(str(exc))
            return
        console.print(f"[bold]{pending.question}[/bold]")
        if pending.plain:
            console.print(f"[cyan]what this means:[/cyan] {pending.plain}")
        for entry in pending.options:
            marker = "→" if entry.key == pending.recommendation else " "
            console.print(f"  {marker} {entry.key}: {entry.label}")
        option = typer.prompt("choose", default=pending.recommendation or pending.options[0].key)
    try:
        message = application.orchestrator.apply_decision(decision_id, option, note)
    except OrkestraError as exc:
        application.close()
        _fail(str(exc))
        return
    console.print(f"[green]✓[/green] {message}")
    application.close()


# ---------------------------------------------------- pause/resume/cancel


@app.command()
def pause(run_id: Annotated[str | None, typer.Option("--run")] = None) -> None:
    """Ask a running orchestration to pause after in-flight tasks finish."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    application.orchestrator.request_pause(resolved)
    console.print(f"pause requested for {resolved}")
    application.close()


@app.command()
def cancel(run_id: Annotated[str | None, typer.Option("--run")] = None) -> None:
    """Cancel the run: in-flight agents are terminated."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    application.orchestrator.request_cancel(resolved)
    console.print(f"cancel requested for {resolved}")
    application.close()


@app.command()
def resume(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    offline: Annotated[bool, typer.Option("--offline")] = False,
) -> None:
    """Reconcile state after an interruption or decision and continue."""
    application = _load_app(offline=offline)
    resolved = _pick_run(application, run_id)

    async def _run() -> RunState:
        application.orchestrator._on_event = _progress_callback(application)
        await application.orchestrator.reconcile(resolved)
        return await application.orchestrator.execute(resolved)

    state = asyncio.run(_run())
    _show_status(application, resolved)
    application.close()
    if state is RunState.WAITING_HUMAN:
        console.print("[yellow]still waiting on decisions[/yellow]")
        raise typer.Exit(code=2)
    if state is RunState.FAILED:
        raise typer.Exit(code=1)


# ------------------------------------------------------------ diff/merge


@app.command()
def diff(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    full: Annotated[bool, typer.Option("--full", help="Full patch, not just stats.")] = False,
) -> None:
    """Show what a run built (against the base it started from)."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    run = application.store.get_run(resolved)
    if not run.integration_branch or not run.base_commit:
        application.close()
        _fail(f"run {resolved} has no integrated results yet")
        return

    async def _run() -> None:
        from orkestra.workspace.git import GitRepo

        repo = GitRepo(application.root)
        _, log, _ = await repo._git(
            "log", "--oneline", f"{run.base_commit}..{run.integration_branch}"
        )
        commits = [line for line in log.splitlines() if line.strip()]
        console.print(
            f"[bold]run {resolved}[/bold] — {len(commits)} commit(s) on {run.integration_branch}\n"
        )
        for line in commits:
            console.print(f"  {line}")
        _, stat, _ = await repo._git(
            "diff", "--stat", f"{run.base_commit}..{run.integration_branch}"
        )
        console.print("\n" + (stat.strip() or "(no file changes)"))
        if full:
            _, patch, _ = await repo._git("diff", f"{run.base_commit}..{run.integration_branch}")
            console.print(patch, highlight=False)
        else:
            console.print(
                "\n[dim]orkestra diff --full for the patch · orkestra merge to accept[/dim]"
            )

    asyncio.run(_run())
    application.close()


@app.command()
def merge(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    cleanup: Annotated[
        bool, typer.Option("--cleanup", help="Delete the run's ork/* branches after merging.")
    ] = False,
) -> None:
    """Accept a run's verified results into your current branch."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    run = application.store.get_run(resolved)
    if not run.integration_branch:
        application.close()
        _fail(f"run {resolved} has no integration branch")
        return
    if run.state is not RunState.COMPLETE:
        console.print(
            f"[yellow]note:[/yellow] run state is '{run.state.value}', not "
            "'complete' — you are merging partial results."
        )

    async def _run() -> None:
        from orkestra.errors import WorkspaceError
        from orkestra.workspace.git import GitRepo

        repo = GitRepo(application.root)
        current = await repo.current_branch()
        if current.startswith("ork/"):
            _fail(f"you are on {current}; switch to your own branch first")
        changed = await repo.tracked_changes()
        if changed:
            _fail(
                "your working tree has uncommitted changes to tracked files "
                f"({', '.join(changed[:5])}) — commit or stash before merging"
            )
        merged = await repo.merge_no_ff(
            run.integration_branch,
            f"Merge orkestra run {resolved} ({run.project_name})",
        )
        if not merged:
            _fail(
                f"merge conflict between {current} and {run.integration_branch} "
                "— your branch moved since the run started. Resolve manually "
                f"with: git merge {run.integration_branch}"
            )
        console.print(f"[green]✓ merged[/green] run {resolved} into [bold]{current}[/bold]")
        if cleanup:
            removed = 0
            for task in application.store.tasks_for_run(resolved):
                branch = f"ork/{resolved}/{task.task_id}"
                try:
                    if await repo.branch_exists(branch):
                        await repo.delete_branch(branch, force=True)
                        removed += 1
                except WorkspaceError:
                    pass
            try:
                await repo.delete_branch(run.integration_branch, force=True)
                removed += 1
            except WorkspaceError:
                pass
            console.print(f"[dim]cleaned up {removed} run branch(es)[/dim]")

    asyncio.run(_run())
    application.close()


# ----------------------------------------------------------------- report


@app.command()
def report(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Write markdown report here.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json-out")] = None,
) -> None:
    """Produce the run report (markdown and/or JSON, secrets redacted)."""
    from orkestra.report.final import build_report, render_json, render_markdown

    application = _load_app()
    resolved = _pick_run(application, run_id)
    document = build_report(application.store, resolved)
    markdown = render_markdown(document)
    if out:
        out.write_text(markdown, encoding="utf-8")
        console.print(f"wrote {out}")
    if json_out:
        json_out.write_text(render_json(document), encoding="utf-8")
        console.print(f"wrote {json_out}")
    if not out and not json_out:
        console.print(markdown)
    application.close()


@app.command()
def watch(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
) -> None:
    """Live TUI monitor for a run (requires the [tui] extra)."""
    try:
        from orkestra.cli.watch import WatchApp
    except ModuleNotFoundError:
        _fail(
            "the TUI needs Textual — install with: "
            "uv tool install 'orkestra-runtime[tui]'  "
            "(or: pip install 'orkestra-runtime[tui]')"
        )
        return
    application = _load_app()
    resolved = _pick_run(application, run_id)
    try:
        WatchApp(application, resolved).run()
    finally:
        application.close()


def main() -> None:  # console-script shim used by some packagers
    app()


if __name__ == "__main__":
    main()

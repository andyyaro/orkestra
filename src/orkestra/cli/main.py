"""Orkestra CLI — the complete operator surface."""

from __future__ import annotations

import asyncio
import shutil
import subprocess  # nosec B404 - argv-only execution, no shell
from collections.abc import Callable
from dataclasses import dataclass as _dataclass
from dataclasses import field as _field
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
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
    import sqlite3

    try:
        application = build_app(offline=offline)
    except ConfigError as exc:
        _fail(str(exc))
        raise AssertionError from None  # unreachable
    except (PermissionError, OSError, sqlite3.OperationalError) as exc:
        _fail(
            f"cannot open the project state ({exc}) — check permissions on the .orkestra/ directory"
        )
        raise AssertionError from None  # unreachable
    _guard_project_not_nested(application)
    return application


def _guard_project_not_nested(application: App) -> None:
    """A project must sit at its repository root. A stray .orkestra/ in a
    subdirectory would make every git operation act on the parent repo."""
    root = application.root.resolve()
    git_exe = shutil.which("git") or "git"
    probe = subprocess.run(  # nosec B603 - fixed argv, no user input
        [git_exe, "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    toplevel = Path(probe.stdout.strip()).resolve() if probe.returncode == 0 else None
    if toplevel is not None and toplevel != root:
        application.close()
        _fail(
            f"this Orkestra project ({root}) sits inside another Git "
            f"repository ({toplevel}), so git operations would act on that "
            "parent project. Move the project to its own directory, or if "
            f"this .orkestra/ folder is a stale leftover, delete it."
        )


def _pick_run(application: App, run_id: str | None) -> str:
    from orkestra.errors import StoreError

    if run_id:
        try:
            application.store.get_run(run_id)
        except StoreError:
            _fail(f"run {run_id!r} not found — `orkestra status` shows the latest run")
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
            tokens = sum(
                (row["input_tokens"] or 0)
                + (row.get("cached_input_tokens") or 0)
                + (row["output_tokens"] or 0)
                for row in usage
            )
            cost = sum(row["total_cost_usd"] or 0 for row in usage)
            cost_text = f" · ${cost:.2f}" if cost else ""
            console.print(
                f"[bold]  ▸ progress: {done}/{len(tasks)} tasks · "
                f"{tokens / 1000:.0f}k tokens{cost_text}[/bold]"
            )

    return callback


def _is_practice_mode(application: App) -> bool:
    """True when every enabled agent is a built-in fake (practice) agent."""
    enabled = application.config.enabled_agents
    return bool(enabled) and all(a.adapter == "fake" for a in enabled.values())


_PRACTICE_NOTE = (
    "  [yellow]practice run:[/yellow] the built-in practice agents demonstrate "
    "the workflow with placeholder files — your SPEC.md is not actually "
    "implemented. Sign in to two real agent CLIs and rerun "
    "[bold]orkestra start[/bold] for real results."
)


def _print_completion(application: App, run_id: str) -> None:
    """Friendly end-of-run message: outcomes, not internals."""
    summary = asyncio.run(_gather_run_summary(application, run_id))
    if _is_practice_mode(application):
        console.print(
            "\n[green bold]Practice run complete — the whole workflow works "
            "end to end.[/green bold]"
        )
        console.print(_PRACTICE_NOTE)
    else:
        # "verified" only when verification actually ran.
        word = "verified" if application.config.verify.commands else "reviewed"
        console.print(f"\n[green bold]Run complete — your {word} result is ready.[/green bold]")
    console.print(f"  tasks: {summary.done}/{summary.total} finished")
    if application.config.verify.commands:
        console.print("  verification: passed (your test commands, run by Orkestra)")
    else:
        console.print(
            "  verification: [yellow]skipped — no test commands configured[/yellow] "
            "(add some under \\[verify] in .orkestra/config.toml)"
        )
    if summary.reviews_required:
        console.print("  review: every change approved by an independent agent")
    if summary.open_decisions:
        console.print("  decisions you resolved along the way: see `orkestra decisions --all`")
    usage = application.store.usage_summary(run_id)
    tokens = sum(
        (row["input_tokens"] or 0)
        + (row.get("cached_input_tokens") or 0)
        + (row["output_tokens"] or 0)
        for row in usage
    )
    cost = sum(row["total_cost_usd"] or 0 for row in usage)
    line = f"  usage: {tokens / 1000:.0f}k tokens"
    if cost:
        line += f" · ${cost:.2f} (agents that report cost)"
    console.print(line)
    console.print(
        "\nYour result is held outside your branches until you accept it."
        "\nNext:\n  [bold]orkestra review[/bold]   see exactly what changed"
        "\n  [bold]orkestra accept[/bold]   bring it into your branch"
    )


def _print_event(_run_id: str, event: AgentEvent) -> None:
    styles = {
        EventKind.ERROR: "red",
        EventKind.WARNING: "yellow",
        EventKind.COMPLETED: "green",
        EventKind.STARTED: "cyan",
    }
    style = styles.get(event.kind)
    text = escape(event.text.strip().replace("\n", " ")[:220])
    if not text:
        return
    label = event.kind.value
    # Attribute streamed events to the agent that produced them; without
    # this, non-TTY logs are unattributable "tool Bash" lines.
    who = str(event.data.get("agent") or "") if event.data else ""
    prefix = f"{label:>9}"
    if who:
        prefix = f"{label:>9} [{escape(who)}]"
    if style:
        console.print(f"[{style}]{prefix}[/{style}] {text}", highlight=False)
    elif event.kind in (EventKind.TEXT, EventKind.TOOL):
        console.print(f"[dim]{prefix} {text}[/dim]", highlight=False)


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
        from orkestra.cli.start import _guard_not_nested

        repo = GitRepo(root)
        if not await repo.is_repo():
            await repo.init()
            console.print("initialized Git repository")
        else:
            _guard_not_nested(root, await repo.toplevel())
        from orkestra.cli.start import _suggested_ignores

        gitignore = root / ".gitignore"
        existing = gitignore.read_text() if gitignore.exists() else ""
        additions = [line for line in _suggested_ignores(root) if line not in existing.split("\n")]
        if additions:
            gitignore.write_text(
                existing
                + ("\n" if existing and not existing.endswith("\n") else "")
                + "# Orkestra local state (never commit) + build artifacts\n"
                + "\n".join(additions)
                + "\n"
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
                "found tests — pre-filled \\[verify] commands (check they run): "
                + ", ".join(f"`{c}`" for c in verify_commands)
            )
        else:
            console.print(
                "[yellow]no test commands detected[/yellow] — add your own to "
                "\\[verify] in .orkestra/config.toml; they are the safety net "
                "agents cannot talk past"
            )
        spec_path = root / "SPEC.md"
        if not spec_path.exists():
            spec_path.write_text(SPEC_TEMPLATE.format(name=root.name))
            console.print(f"created {spec_path.name} — describe your project there")
        # Allowlist-scoped: only files Orkestra itself writes. Any
        # pre-existing user files stay exactly as they were.
        if not await repo.has_commits() and await repo.commit_paths(
            [".gitignore", "SPEC.md"], "orkestra init"
        ):
            console.print("created initial commit (Orkestra setup files only)")
        console.print(f"[green]✓[/green] project initialized at {root}")
        found = [name for name, ok in detected.items() if ok]
        console.print(
            f"detected agent CLIs: {', '.join(found) or 'none'} — "
            "run `orkestra doctor` to verify readiness"
        )

    asyncio.run(_setup())


@app.command()
def start(
    path: Annotated[Path, typer.Argument(help="Project directory.")] = Path(),
    preset: Annotated[
        str | None,
        typer.Option("--preset", help="faster | balanced | max-quality | custom"),
    ] = None,
    non_interactive: Annotated[
        bool, typer.Option("--non-interactive", help="No prompts; sensible defaults.")
    ] = False,
    run_now: Annotated[
        bool | None,
        typer.Option("--run/--no-run", help="Run immediately after setup."),
    ] = None,
    agents: Annotated[
        str | None,
        typer.Option(
            "--agents",
            help="Only enable these agents (comma-separated, e.g. claude,codex).",
        ),
    ] = None,
) -> None:
    """Guided setup: agents, preset, models, gates, spec — then run."""
    from orkestra.cli.start import start_flow

    try:
        should_run, practice_mode = asyncio.run(
            start_flow(
                path,
                interactive=not non_interactive,
                preset_key=preset,
                run_after=run_now,
                agent_filter=agents,
            )
        )
    except ConfigError as exc:
        _fail(str(exc))
        return
    except typer.Abort:
        console.print()
        _fail(
            "setup needs answers, but input ended before it finished — "
            "piping input or scripting this? use --non-interactive, or run "
            "it in a real terminal"
        )
        return
    if should_run:
        import os

        os.chdir(path.resolve())
        # Practice mode uses fake agents: plan heuristically, spend nothing.
        run(spec=None, offline=practice_mode, watch=False)
    else:
        console.print(
            "next: [bold]orkestra run[/bold] (add --watch for the live view) · "
            "then [bold]orkestra review[/bold] and [bold]orkestra accept[/bold]"
        )
        console.print(
            "[dim]if you edit SPEC.md first, commit the edit — runs only "
            "start from committed code[/dim]"
        )


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
    from orkestra.app import find_project_root

    try:
        find_project_root()
    except ConfigError:
        # No project here — still useful: check the environment itself so
        # a first-time user gets real signal instead of a hard error.
        console.print(
            "[yellow]No Orkestra project found here[/yellow] — checking the "
            "environment only. Set one up with [bold]orkestra start[/bold]."
        )
        git_path = shutil.which("git")
        console.print(
            f"  git: {'[green]ok[/green] ' + git_path if git_path else '[red]missing[/red]'}"
        )
        for label, exe in (
            ("claude (Claude Code)", "claude"),
            ("codex (Codex CLI)", "codex"),
            ("agy (Antigravity)", "agy"),
            ("gemini (Gemini CLI)", "gemini"),
        ):
            found = shutil.which(exe)
            status = "[green]on PATH[/green]" if found else "[dim]not found[/dim]"
            console.print(f"  {label}: {status}")
        raise typer.Exit(code=1) from None
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
        for column in (
            "Name",
            "Adapter",
            "Model",
            "Effort",
            "Version",
            "Available",
            "Auth",
            "Notes",
        ):
            table.add_column(column, overflow="fold", max_width=44)
        for name, adapter in application.adapters.items():
            info = await adapter.detect()
            auth = await adapter.check_auth()
            agent_config = application.config.agents[name]
            table.add_row(
                name,
                adapter.adapter_id,
                agent_config.model or "default",
                agent_config.effort or "—",
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


@agents_app.command("set")
def agents_set(
    name: Annotated[str, typer.Argument(help="Agent name from your config.")],
    model: Annotated[str | None, typer.Option("--model", help="Model for this agent.")] = None,
    effort: Annotated[
        str | None,
        typer.Option("--effort", help="Reasoning effort: auto | low | medium | high | max."),
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Remove model and effort overrides.")
    ] = False,
) -> None:
    """Pick an agent's model and effort without hand-editing TOML."""
    import tomlkit

    from orkestra.app import find_project_root
    from orkestra.schemas.config import load_config

    try:
        root = find_project_root(None)
    except ConfigError as exc:
        _fail(str(exc))
        return
    config_path = root / CONFIG_RELPATH
    original = config_path.read_text(encoding="utf-8")
    document = tomlkit.parse(original)
    agents_table = document.get("agents")
    if agents_table is None or name not in agents_table:
        configured = ", ".join(agents_table.keys()) if agents_table else "none"
        _fail(f"no agent named {name!r} in your config (configured: {configured})")
        return
    if not clear and model is None and effort is None:
        _fail("nothing to change — pass --model and/or --effort (or --clear)")
        return
    entry = agents_table[name]
    if clear:
        entry.pop("model", None)
        entry.pop("effort", None)
    if model is not None:
        entry["model"] = model
    if effort is not None:
        entry["effort"] = effort
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        config_path.write_text(original, encoding="utf-8")  # rollback
        _fail(f"change rejected (config rolled back):\n{exc}")
        return
    agent = config.agents[name]
    console.print(
        f"[green]✓[/green] {name} ({agent.adapter}): model="
        f"{agent.model or '[dim]adapter default[/dim]'} · effort="
        f"{agent.effort or '[dim]auto[/dim]'}"
    )


@agents_app.command("models")
def agents_models() -> None:
    """What you can pass to `orkestra agents set --model` per agent."""
    application = _load_app()

    async def _run() -> None:
        from orkestra.adapters.runner import run_capture

        for name, agent_config in application.config.enabled_agents.items():
            adapter = agent_config.adapter
            current = agent_config.model or "(adapter default)"
            console.print(f"\n[bold]{name}[/bold] ({adapter}) — current: {current}")
            if adapter == "antigravity-cli":
                executable = application.adapters[name].which()
                if executable:
                    code, out, _ = await run_capture([executable, "models"], timeout_s=30)
                    if code == 0 and out.strip():
                        for line in out.strip().splitlines():
                            console.print(f"  {line}")
                        console.print("  [dim]effort: low | medium | high[/dim]")
                        continue
                console.print("  [dim](sign in to agy to list models live)[/dim]")
            elif adapter == "claude-code":
                console.print(
                    "  aliases: fable | opus | sonnet | haiku  "
                    "[dim](or any full model name your plan supports)[/dim]"
                )
            elif adapter == "codex-cli":
                console.print(
                    "  any model id your ChatGPT plan supports "
                    "[dim](see /model inside codex; effort: low | medium | high)[/dim]"
                )
            elif adapter == "gemini-cli":
                console.print("  aliases: auto | pro | flash | flash-lite")
            else:
                console.print("  [dim]model selection is up to your external agent[/dim]")

    asyncio.run(_run())
    application.close()


@app.command()
def models() -> None:
    """Your agent lineup: profile, model, effort, availability, provenance."""
    application = _load_app()

    async def _run() -> None:
        from orkestra.adapters.models import discover_models, model_provenance

        table = Table(title="agent profiles")
        for column in ("Profile", "Adapter", "Model", "Effort", "Available", "Model source"):
            table.add_column(column, overflow="fold", max_width=40)
        for name, agent_config in application.config.enabled_agents.items():
            adapter = application.adapters[name]
            info = await adapter.detect()
            auth = await adapter.check_auth()
            catalog = await discover_models(adapter, application.root)
            provenance = model_provenance(agent_config.model, catalog)
            available = (
                "[green]ready[/green]"
                if info.available and auth.ready
                else "[yellow]not ready[/yellow]"
            )
            table.add_row(
                name,
                agent_config.adapter,
                agent_config.model or "[dim]adapter default[/dim]",
                agent_config.effort or "[dim]auto[/dim]",
                available,
                provenance,
            )
        console.print(table)
        console.print(
            "[dim]change with: orkestra agents set <profile> --model … --effort … · "
            "options: orkestra agents models[/dim]"
        )

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

    async def _run() -> tuple[str, RunState]:
        application.orchestrator._on_event = _progress_callback(application)
        run_id = await _prepare()
        return run_id, await application.orchestrator.execute(run_id)

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
        if state is RunState.CANCELLED:
            raise typer.Exit(code=3)
        raise typer.Exit(code=1 if state is RunState.FAILED else 0)

    try:
        executed_run, state = asyncio.run(_run())
    except OrkestraError as exc:
        application.close()
        _fail(str(exc))
        return
    # Always report on the run THIS process executed — a concurrent
    # process may have created a newer run in the meantime.
    _show_status(application, executed_run)
    application.close()
    if state is RunState.COMPLETE:
        reopened = build_app(root=None)
        try:
            _print_completion(reopened, executed_run)
        finally:
            reopened.close()
    elif state is RunState.WAITING_HUMAN:
        console.print(
            "\n[yellow]run is waiting on your decision[/yellow] — "
            "see `orkestra decisions`, then `orkestra resume`"
        )
        raise typer.Exit(code=2)
    elif state is RunState.CANCELLED:
        console.print("[yellow]run was cancelled[/yellow]")
        raise typer.Exit(code=3)
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


#: A run in an active state with no events for this long is presumed
#: stalled or dead (a hard kill leaves the state mid-flight).
_STALE_AFTER_S = 300


def _run_timing(application: App, run_id: str) -> tuple[str, str]:
    """(timing line, staleness warning) derived from the event trail."""
    from datetime import UTC, datetime

    events = application.store.events_for_run(run_id, limit=1_000_000)
    stamps = [str(e["ts"]) for e in events if e.get("ts")]
    if not stamps:
        return "", ""
    try:
        first = datetime.fromisoformat(min(stamps))
        last = datetime.fromisoformat(max(stamps))
    except ValueError:  # pragma: no cover - defensive
        return "", ""
    seconds = int((last - first).total_seconds())
    span = f"{seconds // 60}m{seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"
    local_start = first.astimezone()
    idle = int((datetime.now(UTC) - last.astimezone(UTC)).total_seconds())
    idle_text = f"{idle // 60}m{idle % 60:02d}s" if idle >= 60 else f"{idle}s"
    line = (
        f"started {local_start.strftime('%H:%M:%S %Z')} · {span} of activity "
        f"· last event {idle_text} ago"
    )
    warning = ""
    active = application.store.get_run(run_id).state.value in (
        "created",
        "analyzing",
        "probing",
        "planning",
        "running",
    )
    if active and idle > _STALE_AFTER_S:
        warning = (
            f"[yellow]no activity for {idle_text}[/yellow] — if no `orkestra run` "
            "is executing, this run was interrupted: `orkestra resume` continues it"
        )
    return line, warning


def _show_status(application: App, run_id: str) -> None:
    run = application.store.get_run(run_id)
    console.print(f"\n[bold]run {run.run_id}[/bold] — state: {run.state.value}")
    timing, staleness = _run_timing(application, run_id)
    if timing:
        console.print(f"[dim]{timing}[/dim]")
    if staleness:
        console.print(f"  {staleness}")
    if run.state.value in ("created", "analyzing", "probing", "planning"):
        console.print(
            "[dim]still preparing (analysis → capability probes → plan → "
            "cross-challenge); tasks appear once planning finishes[/dim]"
        )
    table = Table(show_lines=False)
    for column in ("Task", "Kind", "State", "Primary", "Reviewers", "Attempts"):
        table.add_column(column, overflow="fold")
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
            # real history, matching `orkestra report` (the row counter is a
            # budget window that a human "retry" resets)
            str(
                sum(
                    1
                    for a in application.store.attempts_for_task(task.task_id)
                    if a.role == "primary"
                )
            ),
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
    full: Annotated[
        bool,
        typer.Option("--full", help="Show complete event text (e.g. verification output)."),
    ] = False,
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
        text = str(event["text"])
        body = text if full else text[:200] + ("…" if len(text) > 200 else "")
        console.print(
            f"[dim]{event['ts'][:19]}[/dim] {event['kind']:>9} {escape(body)}",
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


def _require_active(application: App, run_id: str, *, verb: str) -> None:
    run = application.store.get_run(run_id)
    if run.state in (RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED):
        application.close()
        _fail(
            f"run {run_id} already finished (state: {run.state.value}) — there is nothing to {verb}"
        )


@app.command()
def pause(run_id: Annotated[str | None, typer.Option("--run")] = None) -> None:
    """Ask a running orchestration to pause after in-flight tasks finish."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    _require_active(application, resolved, verb="pause")
    application.orchestrator.request_pause(resolved)
    console.print(f"pause requested for {resolved}")
    application.close()


@app.command()
def cancel(run_id: Annotated[str | None, typer.Option("--run")] = None) -> None:
    """Cancel the run: in-flight agents are terminated."""
    application = _load_app()
    resolved = _pick_run(application, run_id)
    _require_active(application, resolved, verb="cancel")
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

    async def _run() -> tuple[str, RunState]:
        from orkestra.kernel.prepare import prepare_run

        application.orchestrator._on_event = _progress_callback(application)
        run = application.store.get_run(resolved)
        tasks = application.store.tasks_for_run(resolved)
        prep_states = (
            RunState.CREATED,
            RunState.ANALYZING,
            RunState.PROBING,
            RunState.PLANNING,
        )
        if run.state in prep_states and not tasks:
            # Interrupted before planning produced tasks: nothing partial
            # exists to reconcile — re-plan cleanly from the spec, exactly
            # as the docs promise.
            console.print(
                f"[yellow]run {resolved} was interrupted before planning "
                "finished[/yellow] — nothing was half-done; re-planning "
                "from your spec as a fresh run"
            )
            application.store.set_run_state(resolved, RunState.FAILED)
            spec_text = _read_spec(application, None)
            fresh = await prepare_run(application.orchestrator, application.director, spec_text)
            return fresh, await application.orchestrator.execute(fresh)
        await application.orchestrator.reconcile(resolved)
        return resolved, await application.orchestrator.execute(resolved)

    resumed_run, state = asyncio.run(_run())
    _show_status(application, resumed_run)
    application.close()
    if state is RunState.WAITING_HUMAN:
        console.print("[yellow]still waiting on decisions[/yellow]")
        raise typer.Exit(code=2)
    if state is RunState.FAILED:
        raise typer.Exit(code=1)


# ------------------------------------------------------------ diff/merge


@_dataclass
class _RunSummary:
    run: object
    by_state: dict[str, int] = _field(default_factory=dict)
    done: int = 0
    total: int = 0
    complete: bool = False
    commits: list[str] = _field(default_factory=list)
    stat: str = ""
    shortstat: str = ""
    open_decisions: int = 0
    reviews_required: bool = True
    reviews_skipped: int = 0
    dropped_checks: int = 0


async def _gather_run_summary(application: App, resolved: str) -> _RunSummary:
    """Everything review/accept need to describe a run, in one pass."""
    from orkestra.workspace.git import GitRepo

    run = application.store.get_run(resolved)
    repo = GitRepo(application.root)
    tasks = application.store.tasks_for_run(resolved)
    by_state: dict[str, int] = {}
    for task in tasks:
        by_state[task.state.value] = by_state.get(task.state.value, 0) + 1
    commits: list[str] = []
    stat = ""
    shortstat = ""
    if run.integration_branch and run.base_commit:
        _, log, _ = await repo._git(
            "log", "--oneline", f"{run.base_commit}..{run.integration_branch}", check=False
        )
        commits = [line for line in log.splitlines() if line.strip()]
        _, stat, _ = await repo._git(
            "diff", "--stat", f"{run.base_commit}..{run.integration_branch}", check=False
        )
        _, shortstat, _ = await repo._git(
            "diff", "--shortstat", f"{run.base_commit}..{run.integration_branch}", check=False
        )
    open_decisions = application.store.decisions_for_run(resolved, unresolved_only=True)
    events = application.store.events_for_run(resolved, limit=1_000_000)
    reviews_skipped = sum(1 for e in events if "independent review skipped" in str(e["text"]))
    dropped_checks = sum(1 for e in events if "ignoring plan acceptance entry" in str(e["text"]))
    return _RunSummary(
        run=run,
        by_state=by_state,
        done=by_state.get("done", 0),
        total=len(tasks),
        complete=run.state is RunState.COMPLETE,
        commits=commits,
        stat=stat.strip(),
        shortstat=shortstat.strip(),
        open_decisions=len(open_decisions),
        reviews_required=application.config.policy.require_review,
        reviews_skipped=reviews_skipped,
        dropped_checks=dropped_checks,
    )


def _print_review(application: App, resolved: str, summary: _RunSummary, *, full: bool) -> None:
    import asyncio as _asyncio

    run = summary.run
    by_state = summary.by_state
    done, total = summary.done, summary.total
    commits = summary.commits
    console.print(f"[bold]Run {resolved}[/bold] — project {run.project_name}")  # type: ignore[attr-defined]
    if _is_practice_mode(application):
        console.print(_PRACTICE_NOTE)
    state_value = run.state.value  # type: ignore[attr-defined]
    state_style = "green" if summary.complete else "yellow"
    console.print(
        f"  status: [{state_style}]{state_value}[/{state_style}] · {done}/{total} tasks finished"
    )
    others = {k: v for k, v in by_state.items() if k != "done"}
    if others:
        console.print(
            "  not finished: "
            + ", ".join(f"{count} {state}" for state, count in sorted(others.items()))
        )
    base = str(run.base_commit)[:10]  # type: ignore[attr-defined]
    console.print(
        f"  starting point: your code as of commit {base} "
        "[dim](nothing of yours has been changed)[/dim]"
    )
    if summary.complete:
        if application.config.verify.commands:
            console.print(
                "  verification: every finished task passed your test "
                "commands (run by Orkestra, not taken on trust)"
            )
        else:
            console.print(
                "  verification: [yellow]skipped — no test commands "
                "configured[/yellow] (add some under \\[verify] in "
                ".orkestra/config.toml)"
            )
        if summary.reviews_required:
            note = (
                f" ({summary.reviews_skipped} task(s) had no changes to review)"
                if summary.reviews_skipped
                else ""
            )
            console.print(
                "  independent review: every change was approved by a "
                f"different agent than the one that wrote it{note}"
            )
        if summary.dropped_checks:
            console.print(
                f"  [dim]note: {summary.dropped_checks} plan-proposed extra check(s) "
                "were not runnable commands and were skipped — `orkestra logs` "
                "shows them[/dim]"
            )
    if summary.open_decisions:
        console.print(
            f"  [yellow]waiting on you: {summary.open_decisions} open "
            "decision(s) — `orkestra decisions`[/yellow]"
        )
    console.print(
        f"\n  result: {len(commits)} commit(s)"
        + (f" · {summary.shortstat}" if summary.shortstat else "")
    )
    for line in commits[:20]:  # escaped: subjects contain [agent] tags
        console.print(f"    {escape(line)}")
    if len(commits) > 20:
        console.print(f"    … and {len(commits) - 20} more")
    if summary.stat:
        console.print("\n" + summary.stat)
    if not summary.complete:
        console.print(
            "\n[yellow]⚠ This run is not complete[/yellow] — what you see "
            "above is a partial result. `orkestra resume` continues it; "
            "accepting it anyway requires the advanced --allow-partial flag."
        )
    if full:
        from orkestra.workspace.git import GitRepo

        async def _patch() -> str:
            repo = GitRepo(application.root)
            _, patch, _ = await repo._git(
                "diff",
                f"{run.base_commit}..{run.integration_branch}",  # type: ignore[attr-defined]
                check=False,
            )
            return patch

        console.print(_asyncio.run(_patch()), highlight=False)
    else:
        console.print(
            "\n[dim]orkestra review --full shows the whole patch · "
            "orkestra accept brings it into your branch[/dim]"
        )


def _review_impl(run_id: str | None, full: bool) -> None:
    application = _load_app()
    resolved = _pick_run(application, run_id)
    run = application.store.get_run(resolved)
    if not run.integration_branch or not run.base_commit:
        application.close()
        _fail(f"run {resolved} has no results to review yet")
        return
    summary = asyncio.run(_gather_run_summary(application, resolved))
    _print_review(application, resolved, summary, full=full)
    application.close()


@app.command()
def review(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    full: Annotated[bool, typer.Option("--full", help="Show the whole patch.")] = False,
) -> None:
    """See what a run built: status, verification, reviews, and changes."""
    _review_impl(run_id, full)


@app.command()
def diff(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    full: Annotated[bool, typer.Option("--full", help="Show the whole patch.")] = False,
) -> None:
    """Alias of `orkestra review` (kept for advanced users and scripts)."""
    _review_impl(run_id, full)


def _accept_impl(
    run_id: str | None,
    *,
    cleanup: bool,
    yes: bool,
    allow_partial: bool,
) -> None:
    application = _load_app()
    resolved = _pick_run(application, run_id)
    run = application.store.get_run(resolved)
    if not run.integration_branch:
        application.close()
        _fail(f"run {resolved} has no results to accept")
        return

    async def _preflight() -> tuple[_RunSummary, str, list[str], list[str], bool, str, bool]:
        from orkestra.workspace.git import GitRepo

        repo = GitRepo(application.root)
        current = await repo.current_branch()
        if not await repo.branch_exists(run.integration_branch):
            code, log, _ = await repo._git(
                "log", "--oneline", "--grep", f"Accept orkestra run {resolved}", check=False
            )
            state = "accepted" if code == 0 and log.strip() else "missing"
            return _RunSummary(run=None), current, [], [], False, state, False
        code, _, _ = await repo._git(
            "merge-base", "--is-ancestor", run.integration_branch, "HEAD", check=False
        )
        branch_tip = await repo.head_commit(run.integration_branch)
        if code == 0 and branch_tip != run.base_commit:
            return _RunSummary(run=None), current, [], [], False, "accepted", False
        summary = await _gather_run_summary(application, resolved)
        tracked = await repo.tracked_changes()
        untracked = await repo.untracked_files()
        _, names, _ = await repo._git(
            "diff",
            "--name-only",
            f"{run.base_commit}..{run.integration_branch}",
            check=False,
        )
        run_files = {line for line in names.splitlines() if line.strip()}
        colliding = set(run_files) & set(untracked)
        # On case-insensitive filesystems (macOS default), README.md and
        # readme.md are the same file — compare casefolded too.
        root_l = application.root
        if (root_l / ".orkestra").exists() and (root_l / ".ORKESTRA").exists():
            by_fold = {f.casefold(): f for f in run_files}
            colliding |= {by_fold[u.casefold()] for u in untracked if u.casefold() in by_fold}
        collisions = sorted(colliding)
        head = await repo.head_commit()
        branch_moved = head != run.base_commit
        return summary, current, tracked, collisions, branch_moved, "pending", bool(untracked)

    (
        summary,
        current,
        tracked,
        collisions,
        branch_moved,
        accept_state,
        untracked_present,
    ) = asyncio.run(_preflight())
    if current.startswith("ork/"):
        application.close()
        _fail(
            f"you are on {current}, one of Orkestra's internal branches. "
            "Switch to your own branch first: git checkout main"
        )
        return
    if accept_state == "accepted":
        application.close()
        console.print(
            f"run {resolved} is already part of [bold]{current}[/bold] — nothing new to bring in"
        )
        raise typer.Exit(code=0)
    if accept_state == "missing":
        application.close()
        _fail(
            f"the results of run {resolved} are no longer available (their "
            "internal branch was deleted without being accepted). Re-run the "
            "work with `orkestra run`."
        )
        return

    # ---- hard safety refusals -------------------------------------------
    if tracked:
        application.close()
        _fail(
            "you have uncommitted changes to tracked files "
            f"({', '.join(tracked[:5])}). Save them first —\n"
            '  git add -A && git commit -m "my work"\n'
            "or set them aside:  git stash push — then accept again."
        )
        return
    if collisions:
        application.close()
        _fail(
            "these untracked files would be overwritten by the result: "
            f"{', '.join(collisions[:5])}. Move or commit them first."
        )
        return
    if not summary.complete and not allow_partial:
        by_state = summary.by_state
        missing = ", ".join(
            f"{count} {state}" for state, count in sorted(by_state.items()) if state != "done"
        )
        application.close()
        _fail(
            f"run {resolved} is not complete (state: {run.state.value}; "
            f"unfinished: {missing or 'unknown'}). Finish it with "
            "`orkestra resume`, or — if you truly want the partial result — "
            "rerun with the advanced flag --allow-partial."
        )
        return

    # ---- preflight summary + explicit confirmation ----------------------
    commits = summary.commits
    console.print(f"\n[bold]About to accept run {resolved} into [cyan]{current}[/cyan][/bold]")
    if _is_practice_mode(application):
        console.print(_PRACTICE_NOTE)
    console.print(
        f"  run state: {run.state.value} · tasks finished: {summary.done}/{summary.total}"
    )
    console.print(
        f"  changes: {len(commits)} commit(s)"
        + (f" · {summary.shortstat}" if summary.shortstat else "")
    )
    if summary.complete:
        verify_word = "passed" if application.config.verify.commands else "none configured"
        console.print(
            f"  verification: {verify_word} · independent review: "
            + ("approved" if summary.reviews_required else "not required by policy")
        )
    if summary.open_decisions:
        console.print(f"  [yellow]note: {summary.open_decisions} decision(s) still open[/yellow]")
    console.print(
        "  working tree: no uncommitted changes to tracked files"
        + (" (untracked files are left alone)" if untracked_present else "")
    )
    if branch_moved:
        console.print(
            f"  [yellow]note: {current} moved since the run started — a "
            "conflict is possible; conflicts are aborted safely[/yellow]"
        )
    if not summary.complete:
        console.print(
            "  [red]⚠ ACCEPTING A PARTIAL RESULT[/red] — unfinished tasks "
            "will simply be missing from your branch."
        )
    if not yes:
        try:
            proceed = typer.confirm("Proceed with accepting this result?", default=False)
        except typer.Abort:
            application.close()
            console.print()
            _fail(
                "no answer received — running without a terminal? add --yes "
                "to accept without the prompt"
            )
            return
        if not proceed:
            application.close()
            console.print("nothing changed — your branch is untouched")
            raise typer.Exit(code=0)

    async def _merge() -> bool:
        from orkestra.workspace.git import GitRepo

        repo = GitRepo(application.root)
        return await repo.merge_no_ff(
            run.integration_branch,
            f"Accept orkestra run {resolved} ({run.project_name})",
        )

    try:
        merged = asyncio.run(_merge())
    except OrkestraError as exc:

        async def _abort() -> None:
            from orkestra.workspace.git import GitRepo

            await GitRepo(application.root)._git("merge", "--abort", check=False)

        asyncio.run(_abort())
        application.close()
        _fail(
            "the merge hit an unexpected git error and was aborted — "
            f"nothing on your branch was kept from it. Detail: {exc}"
        )
        return
    if not merged:
        application.close()
        _fail(
            f"the result could not be combined with {current} automatically "
            "because your branch changed the same files since the run "
            "started. Nothing was modified — the attempted merge was "
            "aborted and both sides are intact.\n"
            "Next steps:\n"
            f"  git merge {run.integration_branch}   # then resolve the "
            "conflicts it reports\n"
            "or rerun the work on your current code: orkestra run"
        )
        return
    console.print(
        f"[green]✓ accepted[/green] — run {resolved} is now part of [bold]{current}[/bold]"
    )
    if not cleanup:
        console.print(
            "[dim]Orkestra's internal branches are still around; "
            "`orkestra accept --cleanup` removes them next time[/dim]"
        )

    if cleanup:

        async def _cleanup() -> int:
            from orkestra.errors import WorkspaceError
            from orkestra.workspace.git import GitRepo

            repo = GitRepo(application.root)
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
            return removed

        removed = asyncio.run(_cleanup())
        console.print(f"[dim]tidied up {removed} internal branch(es)[/dim]")
    application.close()


@app.command()
def accept(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    cleanup: Annotated[
        bool, typer.Option("--cleanup", help="Tidy up internal branches after accepting.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="Skip the confirmation prompt (automation).")
    ] = False,
    allow_partial: Annotated[
        bool,
        typer.Option(
            "--allow-partial",
            help="ADVANCED, RISKY: accept an incomplete run's partial results.",
        ),
    ] = False,
) -> None:
    """Bring a completed run's verified result into your current branch."""
    _accept_impl(run_id, cleanup=cleanup, yes=yes, allow_partial=allow_partial)


@app.command()
def merge(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    cleanup: Annotated[
        bool, typer.Option("--cleanup", help="Tidy up internal branches after accepting.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="Skip the confirmation prompt (automation).")
    ] = False,
    allow_partial: Annotated[
        bool,
        typer.Option(
            "--allow-partial",
            help="ADVANCED, RISKY: accept an incomplete run's partial results.",
        ),
    ] = False,
) -> None:
    """Alias of `orkestra accept` (kept for advanced users and scripts)."""
    _accept_impl(run_id, cleanup=cleanup, yes=yes, allow_partial=allow_partial)


# ----------------------------------------------------------------- report


@app.command()
def report(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Write markdown report here.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json-out")] = None,
    save: Annotated[
        bool,
        typer.Option(
            "--save",
            help=(
                "Write markdown + JSON under .orkestra/reports/ (git-ignored). "
                "An explicit --out/--json-out keeps its own path; --save fills "
                "in whichever outputs weren't given one."
            ),
        ),
    ] = False,
) -> None:
    """Produce the run report (markdown and/or JSON, secrets redacted)."""
    from orkestra.report.final import build_report, render_json, render_markdown

    application = _load_app()
    resolved = _pick_run(application, run_id)
    document = build_report(application.store, resolved)
    markdown = render_markdown(document)
    if save:
        reports_dir = application.root / ".orkestra" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = out or reports_dir / f"{resolved}.md"
        json_out = json_out or reports_dir / f"{resolved}.json"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        console.print(f"wrote {out}")
        _report_location_note(application.root, out)
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(render_json(document), encoding="utf-8")
        console.print(f"wrote {json_out}")
        _report_location_note(application.root, json_out)
    if not out and not json_out:
        console.print(markdown)
    application.close()


def _report_location_note(root: Path, path: Path) -> None:
    """Warn when a report lands in the repo as a stray untracked file."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return
    if rel.parts[:1] != (".orkestra",):
        console.print(
            f"[dim]note: {path} sits in your repository as an untracked file — "
            "commit or delete it when done, or use --save to keep reports "
            "under .orkestra/reports/ (git-ignored)[/dim]"
        )


@app.command()
def watch(
    run_id: Annotated[str | None, typer.Option("--run")] = None,
) -> None:
    """Live TUI monitor for a run (requires the 'tui' extra)."""
    try:
        from orkestra.cli.watch import WatchApp
    except ModuleNotFoundError:
        _fail(
            "the TUI needs Textual — install with: "
            "uv tool install 'orkestra-runtime\\[tui]'  "
            "(or: pip install 'orkestra-runtime\\[tui]')"
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

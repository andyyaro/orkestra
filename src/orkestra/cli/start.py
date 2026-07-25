"""`orkestra start` — the guided first-run journey.

One command that takes a newcomer from an empty directory to a running
orchestration without hand-editing TOML or learning internals first:

    init → agents → preset → models/effort → verify commands → spec →
    readiness check → (optionally) run

Progressive disclosure: defaults are one keypress; every advanced knob
is still reachable (custom models, per-profile effort), and everything
written is the same `.orkestra/config.toml` the low-level commands use.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import tomlkit
import typer
from rich.console import Console
from rich.table import Table

from orkestra.adapters import build_adapter
from orkestra.adapters.models import ModelCatalog, discover_models
from orkestra.cli.detect import detect_verify_commands
from orkestra.cli.presets import PRESETS, AgentProfile, Preset, pick_director, profiles_for
from orkestra.schemas.config import AgentConfig, load_config
from orkestra.schemas.effort import ADAPTER_EFFORT

console = Console()

_ADAPTER_EXECUTABLES = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "antigravity-cli": "agy",
    "gemini-cli": "gemini",
}


def _fail(message: str) -> None:
    console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


async def _detect_ready_adapters() -> dict[str, dict[str, str]]:
    """adapter_id -> {version, ready, detail} for CLIs present on PATH."""
    found: dict[str, dict[str, str]] = {}
    for adapter_id, executable in _ADAPTER_EXECUTABLES.items():
        if not shutil.which(executable):
            continue
        adapter = build_adapter("probe", AgentConfig(adapter=adapter_id))
        info = await adapter.detect()
        auth = await adapter.check_auth()
        found[adapter_id] = {
            "version": info.version,
            "ready": "yes" if (info.available and auth.ready) else "no",
            "detail": (info.detail or auth.detail)[:80],
        }
    return found


def _choose_preset(interactive: bool, preset_key: str | None) -> Preset:
    if preset_key:
        if preset_key not in PRESETS and preset_key != "custom":
            _fail(f"unknown preset {preset_key!r} — options: " + ", ".join([*PRESETS, "custom"]))
        if preset_key != "custom":
            return PRESETS[preset_key]
        if not interactive:
            _fail(
                "--preset custom means picking models and effort yourself, "
                "which needs the interactive wizard. Drop --non-interactive, "
                "or use faster | balanced | max-quality and edit "
                ".orkestra/config.toml afterwards."
            )
    if not interactive:
        return PRESETS["balanced"]
    console.print("\n[bold]How should the agents be tuned?[/bold]")
    keys = list(PRESETS)
    for index, key in enumerate(keys, 1):
        preset = PRESETS[key]
        console.print(f"  {index}. {preset.label} — [dim]{preset.description}[/dim]")
    console.print(f"  {len(keys) + 1}. Custom — pick models and effort per agent")
    choice = typer.prompt("choose", default="2")
    try:
        number = int(choice)
    except ValueError:
        number = 2
    if number == len(keys) + 1:
        return PRESETS["balanced"]  # custom starts from balanced, then edits
    return PRESETS[keys[max(0, min(number - 1, len(keys) - 1))]]


async def _customize_profiles(
    profiles: list[AgentProfile], root: Path, interactive: bool
) -> list[AgentProfile]:
    if not interactive:
        return profiles
    result: list[AgentProfile] = []
    for profile in profiles:
        console.print(f"\n[bold]{profile.name}[/bold] ({profile.adapter})")
        if not typer.confirm("  enable this agent?", default=True):
            continue
        adapter = build_adapter(profile.name, AgentConfig(adapter=profile.adapter))
        catalog: ModelCatalog = await discover_models(adapter, root)
        model = profile.model
        if catalog.models:
            label = "listed live" if catalog.provenance == "discovered" else "documented"
            console.print(f"  models ({label}):")
            for index, name in enumerate(catalog.models[:12], 1):
                console.print(f"    {index}. {name}")
            console.print("    0. adapter default   ·   a. advanced: type a custom model")
            raw = typer.prompt("  model", default="0")
            if raw.strip().lower() == "a":
                model = typer.prompt("  custom model id")
            elif raw.strip().isdigit() and 1 <= int(raw) <= len(catalog.models[:12]):
                model = catalog.models[int(raw) - 1]
            else:
                model = None
        else:
            console.print(f"  [dim]{catalog.note}[/dim]")
            custom = typer.prompt("  model (blank = adapter default)", default="")
            model = custom.strip() or None
        effort = profile.effort
        support = ADAPTER_EFFORT.get(profile.adapter)
        if support and support.mapping:
            levels = support.supported_levels()
            effort_raw = typer.prompt(f"  effort ({' | '.join(levels)})", default=effort or "auto")
            effort = None if effort_raw.strip() in ("", "auto") else effort_raw.strip()
            if effort and effort not in support.mapping:
                console.print(
                    f"  [yellow]{effort!r} isn't supported here ({support.note}) "
                    "— using auto[/yellow]"
                )
                effort = None
        result.append(replace(profile, model=model, effort=effort))
    return result


def _write_config(
    root: Path,
    project_name: str,
    profiles: list[AgentProfile],
    preset: Preset,
    verify_commands: list[str],
) -> None:
    document = tomlkit.document()
    document.add(tomlkit.comment("Generated by `orkestra start` — edit freely, or use"))
    document.add(tomlkit.comment("`orkestra agents set` / `orkestra start` to reconfigure."))
    document["version"] = 1
    project = tomlkit.table()
    project["name"] = project_name
    project["spec_file"] = "SPEC.md"
    document["project"] = project
    agents = tomlkit.table()
    for profile in profiles:
        entry = tomlkit.table()
        entry["adapter"] = profile.adapter
        if profile.model:
            entry["model"] = profile.model
        if profile.effort:
            entry["effort"] = profile.effort
        if profile.token_budget:
            entry["token_budget"] = profile.token_budget
        agents[profile.name] = entry
    document["agents"] = agents
    director = tomlkit.table()
    director["agent"] = pick_director(profiles)
    document["director"] = director
    policy = tomlkit.table()
    policy["max_concurrency"] = preset.max_concurrency
    document["policy"] = policy
    verify = tomlkit.table()
    verify["commands"] = verify_commands
    document["verify"] = verify
    probes = tomlkit.table()
    probes["mode"] = preset.probes_mode
    probes["budget"] = preset.probes_budget
    document["probes"] = probes
    config_path = root / ".orkestra" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    load_config(config_path)  # raises with a precise message if invalid


def _spec_assist(root: Path, interactive: bool) -> bool:
    """Returns True when Orkestra wrote/updated SPEC.md this invocation."""
    spec_path = root / "SPEC.md"
    existing = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    looks_empty = not existing.strip() or "- ..." in existing
    if not looks_empty:
        return False
    if not interactive:
        if not existing:
            spec_path.write_text(
                f"# {root.name}\n\nDescribe what the agents should build.\n\n"
                "## Goals\n\n## Constraints\n\n## Acceptance\n"
            )
            return True
        return False
    console.print(
        "\n[bold]Describe the work[/bold] [dim](plain sentences; you can edit "
        "SPEC.md any time)[/dim]"
    )
    goal = ""
    while not goal.strip():
        goal = typer.prompt(
            "  what should the agents build or change?", default="", show_default=False
        )
        if not goal.strip():
            console.print(
                "  [yellow]one plain sentence is enough — this can't be "
                "blank (Ctrl-C to stop and edit SPEC.md yourself)[/yellow]"
            )
    boundaries = typer.prompt("  anything they must NOT touch?", default="nothing in particular")
    success = typer.prompt("  how will you judge it's done?", default="the verify commands pass")
    spec_path.write_text(
        f"# {root.name}\n\n## Goals\n\n{goal}\n\n"
        f"## Constraints\n\nDo not touch: {boundaries}.\n\n"
        f"## Acceptance\n\n{success}\n"
    )
    console.print("  [green]✓[/green] SPEC.md written")
    return True


async def start_flow(
    root: Path,
    *,
    interactive: bool,
    preset_key: str | None,
    run_after: bool | None,
) -> tuple[bool, bool]:
    """Returns (run_now, practice_mode)."""
    from orkestra.workspace.git import GitRepo

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)

    # ---- capture repository state BEFORE any mutation (git safety) ----
    was_repo = await repo.is_repo()
    pre_tracked: list[str] = []
    pre_staged: list[str] = []
    pre_untracked: list[str] = []
    had_commits = False
    if was_repo:
        pre_tracked = await repo.tracked_changes()
        pre_staged = await repo.staged_changes()
        pre_untracked = await repo.untracked_files()
        had_commits = await repo.has_commits()
        if pre_tracked or pre_staged:
            # Existing repository with in-progress user work: stop before
            # touching anything. Mixing it into an orchestration baseline
            # could entangle the user's changes with agent work.
            pending = list(dict.fromkeys(pre_staged + pre_tracked))  # dedupe, keep order
            listing = ", ".join(pending[:5])
            more = "" if len(pending) <= 5 else ", …"
            console.print(
                "[yellow]You have work in progress here that isn't committed"
                f"[/yellow] ({listing}{more}).\n\n"
                "Orkestra won't touch it — but it also can't set up a clean "
                "starting point for the agents while it's pending, and "
                "continuing could mix your changes into the agents' work.\n\n"
                "[bold]Save your work first, then rerun this command:[/bold]\n"
                '  git add -A && git commit -m "my work in progress"\n'
                "[dim]or set it aside temporarily:[/dim]\n"
                '  git stash push -m "before orkestra"\n'
            )
            raise typer.Exit(code=1)
    else:
        pre_untracked = [
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
        await repo.init()
        console.print("[green]✓[/green] Git repository created")

    # Files Orkestra itself creates/updates in this invocation — the ONLY
    # things its setup commit may ever contain.
    orkestra_owned: list[str] = []
    gitignore = root / ".gitignore"
    existing_ignore = gitignore.read_text() if gitignore.exists() else ""
    if ".orkestra/" not in existing_ignore.split("\n"):
        gitignore.write_text(
            existing_ignore
            + ("\n" if existing_ignore and not existing_ignore.endswith("\n") else "")
            + ".orkestra/\n"
        )
        orkestra_owned.append(".gitignore")

    console.print("\n[bold]Looking for coding agents on this machine…[/bold]")
    ready = await _detect_ready_adapters()
    table = Table(show_header=True)
    for column in ("Agent CLI", "Version", "Signed in", "Note"):
        table.add_column(column, overflow="fold", max_width=46)
    for adapter_id, info in ready.items():
        table.add_row(adapter_id, info["version"], info["ready"], info["detail"])
    if ready:
        console.print(table)
    usable = [a for a, info in ready.items() if info["ready"] == "yes"]
    practice_mode = len(usable) < 2
    if practice_mode:
        console.print(
            "[yellow]Fewer than two agents are signed in[/yellow] — setting up "
            "[bold]practice mode[/bold] with built-in fake agents so you can "
            "try the whole journey now. Sign in to real CLIs later and rerun "
            "`orkestra start`."
        )

    preset = _choose_preset(interactive, preset_key)
    console.print(f"[green]✓[/green] preset: {preset.label}")

    if practice_mode:
        profiles = [
            AgentProfile("ada", "fake"),
            AgentProfile("grace", "fake"),
        ]
    else:
        profiles = profiles_for(preset, usable)
        wants_custom = interactive and (preset_key == "custom" or preset_key is None)
        if (
            wants_custom
            and interactive
            and typer.confirm(
                "customize models/effort per agent?", default=(preset_key == "custom")
            )
        ):
            profiles = await _customize_profiles(profiles, root, interactive)
        if len(profiles) < 2:
            _fail("at least two enabled agents are needed — enable more and retry")

    verify_commands = detect_verify_commands(root)
    if verify_commands:
        console.print(
            "[green]✓[/green] verification commands detected: "
            + ", ".join(f"`{c}`" for c in verify_commands)
        )
        if interactive and not typer.confirm("  use these as the quality gate?", default=True):
            raw = typer.prompt("  commands (comma-separated)", default="")
            verify_commands = [c.strip() for c in raw.split(",") if c.strip()]
    elif interactive:
        raw = typer.prompt(
            "no test commands detected — enter any (comma-separated, blank to skip)",
            default="",
        )
        verify_commands = [c.strip() for c in raw.split(",") if c.strip()]

    project_name = root.name.lower().replace(" ", "-") or "project"
    _write_config(root, project_name, profiles, preset, verify_commands)
    console.print(
        "[green]✓[/green] .orkestra/config.toml written "
        "[dim](plain TOML — advanced users can edit it directly)[/dim]"
    )

    if _spec_assist(root, interactive):
        orkestra_owned.append("SPEC.md")

    # Setup commit: pathspec-scoped to Orkestra-owned files only. The
    # user's tracked, staged, and untracked files are never included.
    if orkestra_owned:
        sha = await repo.commit_paths(orkestra_owned, "orkestra start")
        if sha:
            committed = await repo.commit_files_in(sha)
            unexpected = [f for f in committed if f not in orkestra_owned]
            if unexpected:  # defensive: structural guarantee, verified anyway
                msg = f"setup commit unexpectedly included {unexpected}"
                raise RuntimeError(msg)
            console.print(
                "[green]✓[/green] committed Orkestra setup files "
                f"({', '.join(committed)}) — nothing else"
            )

    baseline_missing = not had_commits and bool(pre_untracked)
    if baseline_missing:
        console.print(
            f"\n[yellow]Your {len(pre_untracked)} existing file(s) are not "
            "committed yet[/yellow] — agents work from committed code, so "
            "save them as the starting point before running:\n"
            '  git add . && git commit -m "project baseline"\n'
            "then: [bold]orkestra run[/bold]"
        )
        run_after = False

    names = ", ".join(p.name for p in profiles)
    console.print(f"\n[bold]Ready.[/bold] Agents: {names} · preset: {preset.label}")
    if run_after is None and interactive:
        run_after = typer.confirm("start the first run now?", default=True)
    return bool(run_after), practice_mode

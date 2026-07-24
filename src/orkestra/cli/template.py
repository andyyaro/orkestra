"""Configuration template written by `orkestra init`."""

from __future__ import annotations

CONFIG_TEMPLATE = """\
# Orkestra project configuration.
# Reference: https://github.com/andyyaro/orkestra/blob/main/docs/CONFIGURATION.md
version = 1

[project]
name = "{name}"
# Markdown specification the director plans from (orkestra run/plan read it).
spec_file = "SPEC.md"

# ---------------------------------------------------------------------------
# Agents. At least two enabled agents are required; add as many as you like.
# Adapters: claude-code | codex-cli | antigravity-cli | gemini-cli | fake | external
# ---------------------------------------------------------------------------
{agents}
# Example: a third-party agent speaking the orkestra-jsonl/1 protocol.
# [agents.myagent]
# adapter = "external"
# command = ["/usr/local/bin/my-agent", "--headless"]

[director]
# Which agent leads analysis, planning, and arbitration (default: claude).
agent = "{director}"

[policy]
max_concurrency = 2
max_attempts_per_task = 3
max_review_cycles = 2
require_review = true
allow_push = false          # Orkestra never pushes unless you opt in
task_timeout_s = 1800
# sandbox = "docker"        # opt-in extra isolation (experimental)

[verify]
# Deterministic acceptance commands run by the kernel after each mutating
# task. Agents cannot override these gates.
commands = [{verify}]

[probes]
# live = spend a little quota measuring agents; cached = reuse results per
# agent version; off = skip probing (heuristic/offline assignment only).
mode = "cached"
budget = 6
"""

AGENT_BLOCK = """\
[agents.{name}]
adapter = "{adapter}"
enabled = {enabled}
{extra}
"""


def render_config(
    project_name: str,
    detected: dict[str, bool],
    verify_commands: list[str] | None = None,
) -> str:
    """Render the init template. `detected` maps agent name -> on PATH."""
    adapter_by_name = {
        "claude": "claude-code",
        "codex": "codex-cli",
        "antigravity": "antigravity-cli",
        "gemini": "gemini-cli",
    }
    blocks = []
    for name, adapter in adapter_by_name.items():
        on_path = detected.get(name, False)
        if name == "gemini":
            extra = (
                "# Requires GEMINI_API_KEY / Vertex auth; consumer Google\n"
                "# accounts are served by antigravity-cli instead.\n"
            )
            enabled = "false"
        else:
            extra = "" if on_path else "# (not found on PATH at init time)\n"
            enabled = "true"
        blocks.append(AGENT_BLOCK.format(name=name, adapter=adapter, enabled=enabled, extra=extra))
    verify = ", ".join(f'"{c}"' for c in (verify_commands or []))
    return CONFIG_TEMPLATE.format(
        name=project_name,
        agents="\n".join(blocks),
        director="claude",
        verify=verify,
    )


SPEC_TEMPLATE = """\
# {name}

Describe what you want the agents to build. Orkestra's director reads this
file, decomposes it into a task graph, and delegates the work.

## Goals

- ...

## Constraints

- ...

## Acceptance

- ...
"""

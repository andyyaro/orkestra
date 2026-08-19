# Configuration Reference

Location: `.orkestra/config.toml` (project-local, created by
`orkestra init` or `orkestra start`, discovered by walking up from the current directory).
Validation is strict: unknown keys are errors with precise messages.

```toml
version = 1                      # config schema version (required)
```

## `[project]`

| Key | Default | Meaning |
|---|---|---|
| `name` | - (required) | Project slug (`[a-z0-9._-]`, ≤64 chars) |
| `spec_file` | `"SPEC.md"` | Markdown specification read by `plan`/`run` |

## `[agents.<name>]` - one table per agent; **≥ 2 enabled required**

| Key | Default | Meaning |
|---|---|---|
| `adapter` | - (required) | `claude-code`, `codex-cli`, `antigravity-cli`, `gemini-cli`, `fake`, or `external` |
| `enabled` | `true` | Disabled agents are ignored entirely |
| `model` | adapter default | Model override passed to the CLI (easiest: `orkestra agents set NAME --model …`) |
| `effort` | `auto` | Provider-neutral `auto`/`low`/`medium`/`high`/`max`, validated against the adapter's real capabilities (unsupported levels are rejected with an explanation; e.g. Claude Code has no effort control - pick a model tier instead) |
| `run_commands` | `false` | Let this agent run shell commands inside its isolated worktree. Off by default: Orkestra runs your `[verify]` commands itself, and headless agents cannot answer permission prompts - leaving it off avoids agents burning turns asking. Turn it on to let an agent self-check before handing work back. |
| `autonomy` | `"safe"` | `safe` = workspace-scoped edit autonomy via the CLI's own safety system; `unsafe-full` = the CLI's bypass mode (explicit opt-in, logged) |
| `timeout_s` | `1800` | Per-attempt wall clock (30–86400) |
| `token_budget` | unlimited | Max input+output tokens this agent may spend per run (≥1000). Once exceeded, the kernel stops dispatching new work to it (reviews still allowed) and uses fallbacks |
| `sandbox_image` | - | Container image this agent runs in when `policy.sandbox = "docker"` (external/fake adapters only) |
| `command` | - | **external adapter only**: argv of your agent binary |

Multiple profiles of the same adapter are valid (e.g. two `claude-code`
agents with different models).

## `[director]`

| Key | Default | Meaning |
|---|---|---|
| `agent` | `"claude"` | Which configured agent leads analysis/planning/arbitration; must be enabled. Any adapter with structured-output support works; without it Orkestra falls back to heuristic planning |
| `max_decision_retries` | `2` | Schema-repair retries per director exchange (0–5) |

## `[policy]`

| Key | Default | Meaning |
|---|---|---|
| `max_concurrency` | `2` | Parallel tasks (1–32). Remember: parallel agents multiply your subscription usage |
| `max_attempts_per_task` | `3` | Attempt budget incl. fallbacks (1–10) |
| `max_review_cycles` | `2` | Review→fix loops per task (0–5) |
| `require_review` | `true` | Independent review gate for mutating tasks |
| `session_reuse` | `true` | Resume the same agent's CLI session on fix-cycle retries in the same workspace (quota saver); sessions never cross agents or workspaces |
| `allow_push` | `false` | Orkestra never pushes unless this is true |
| `task_timeout_s` | `1800` | Kernel-enforced ceiling per attempt |
| `protected_paths` | `[".git", ".orkestra", ".github/workflows"]` | Diffs touching these are rejected |
| `sandbox` | `"none"` | `"docker"` runs **external/fake agents** in hardened containers (no network, cap-drop ALL, read-only rootfs, non-root, worktree-only mount). Vendor CLIs are refused with an explanation - ADR-0009 |

## `[verify]`

| Key | Default | Meaning |
|---|---|---|
| `commands` | `[]` | Deterministic acceptance commands (parsed with shlex, run without a shell, exit codes inspected by the kernel). These always run and are the authoritative gate; plan-generated `acceptance` entries run in addition to them and only when they validate as runnable commands. A command that cannot start is caught in pre-flight, before any agent is dispatched |
| `timeout_s` | `900` | Per-command timeout |

## `[probes]`

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"cached"` | `live` (always spend), `cached` (reuse per agent version), `off` |
| `budget` | `6` | Max live probe invocations per run across all agents |
| `timeout_s` | `240` | Per-probe timeout |

## Example: two agents

```toml
version = 1
[project]
name = "myapp"
[agents.claude]
adapter = "claude-code"
[agents.codex]
adapter = "codex-cli"
[verify]
commands = ["pytest -q"]
```

## Example: three agents, custom director model

```toml
version = 1
[project]
name = "myapp"
[agents.claude]
adapter = "claude-code"
model = "sonnet"
[agents.codex]
adapter = "codex-cli"
[agents.antigravity]
adapter = "antigravity-cli"
[director]
agent = "claude"
[verify]
commands = ["pytest -q", "ruff check ."]
```

## Example: four+ agents including a third-party adapter

```toml
version = 1
[project]
name = "myapp"
[agents.claude]
adapter = "claude-code"
[agents.codex]
adapter = "codex-cli"
[agents.antigravity]
adapter = "antigravity-cli"
[agents.inhouse]
adapter = "external"
command = ["/opt/agents/inhouse", "--headless"]
[policy]
max_concurrency = 3
```

## Secrets

Config files carry no secrets by design; agent auth lives with each
vendor CLI. `GEMINI_API_KEY` (gemini-cli only) is read from the
environment, never from config, and is passed only to that adapter's
subprocess.

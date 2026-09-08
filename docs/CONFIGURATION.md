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
| `binding_check` | `true` | Prove, once per run and before any agent is dispatched, that the gate actually reads the tree it is pointed at (see below). Costs two extra gate runs per run |

### Unbound gates: when a green gate proves nothing

Orkestra runs your commands with the working directory set to a task's
isolated worktree, and then treats exit 0 as a statement *about that
worktree*. That inference is not automatic. The classic way it fails:

```
$ cat .venv/lib/python3.12/site-packages/_editable_impl_myproj.pth
/home/me/myproj/src
```

An editable install of a src-layout project writes an **absolute** path to
the checkout it was installed from. That path is on `sys.path` for every
process using that interpreter, whatever the working directory is. So
`pytest -q`, run inside a worktree, imports and tests the code in your main
checkout. Replace a file in the worktree with `raise RuntimeError` and the
gate still exits 0. The gate is *unbound*: it returns green on a tree it
never read, silently, always.

Two things make this worth naming. It is the default modern Python layout,
and the failure is false-clean, so nothing downstream can notice.

Orkestra defends in three ways:

1. It prepends a worktree-scoped `PYTHONPATH` (the worktree's `src/`, then
   the worktree root) when it runs your commands, so the common Python case
   is bound by construction.
2. Before the first agent is dispatched, it corrupts one tracked source
   file in a throwaway worktree and requires your gate's exit code to
   change. If it does not, the run stops with a config defect, exactly as a
   `[verify]` command that cannot start does. Turn this off with
   `binding_check = false` if your suite is too slow to run twice.
3. `orkestra doctor` reports the same three facts (commands resolve, the
   gate passes in a fresh checkout of HEAD, the gate is bound) before you
   spend anything.

Writing a gate that binds:

- **Good:** `uv run pytest -q` - re-resolves the environment for the
  current directory.
- **Acceptable:** `python3 -m pytest -q` - puts the current directory first
  on `sys.path`, which is enough for a flat layout.
- **Risky on its own:** `pytest -q` - the console script resolves imports
  through its own interpreter, wherever that points.

A gate that cannot be *proved* bound is reported as CANNOT-CHECK, which is
distinct from both a pass and a failure and is never reported as a pass. A
gate that cannot fail for any code reason (`test -f README.md`) is reported
as unbound too, because it means the same thing: this exit code is not
evidence.

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
commands = ["uv run pytest -q"]
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
commands = ["uv run pytest -q", "uv run ruff check ."]
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

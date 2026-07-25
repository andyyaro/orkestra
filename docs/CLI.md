# CLI Reference

`orkestra --version` · `orkestra --help` · every command accepts `--help`.

Commands find the project by walking up from the current directory to
the nearest `.orkestra/config.toml`.

## Try it first

### `orkestra demo [--path DIR]`

Free, zero-quota showcase: scripted fake agents drive the real kernel
through planning, parallel isolated tasks, a verification gate, a review
rejection + repair, and integration — in under a minute. The best first
command.

## The guided journey

### `orkestra start [PATH] [--preset faster|balanced|max-quality|custom] [--non-interactive] [--run/--no-run] [--agents claude,codex]`

Everything from zero to running: Git setup, agent detection, preset or
per-agent model/effort selection (with live model discovery where the
CLI supports it), verification-command confirmation, spec assistance,
and an optional immediate run. With fewer than two signed-in agents it
configures practice mode (fake agents) so the journey always works.
`--agents` restricts setup to the named agents instead of enabling
every signed-in CLI (friendly names accepted: claude, codex,
antigravity/agy, gemini — at least two required); if a requested agent
isn't signed in, start stops with an explanation rather than silently
substituting. Both `start` and `init` refuse to set up a project inside
a subdirectory of an existing Git repository (git would resolve every
command to the parent repo) — run them at that repository's root or
place the project elsewhere.
Re-running it on an existing project reconfigures without destroying
your spec. Presets tune models, effort, probes, concurrency — never
verification or independent review.

### `orkestra models`

Your lineup at a glance: profile, adapter, model, effort, availability,
and where each model value came from (discovered / documented / manual /
default).

## Project setup

### `orkestra init [PATH] [--non-interactive]`

Initialize a project: create/verify the Git repo, write
`.orkestra/config.toml` (agents pre-enabled based on what's on your
PATH), create a `SPEC.md` template, gitignore `.orkestra/`, and make an
initial commit if the repo has none. Refuses to overwrite an existing
config.

### `orkestra doctor`

Readiness checks with actionable fixes: git + worktree support,
repository state, config validity, state database, each agent's
availability/version/auth, and optional Docker presence. Exit code 1 if
fewer than two agents are ready or any hard check fails.

## Agents

### `orkestra agents list`

Table of configured agents: adapter, version, availability, auth
readiness, notes (including provider caveats).

### `orkestra agents set NAME [--model M] [--effort auto|low|medium|high|max] [--clear]`

Pick an agent's model and reasoning effort without editing TOML — the
config file is rewritten comment-preservingly and validated (invalid
changes roll back). Effort is provider-neutral (`auto | low | medium |
high | max`) and hard-validated per adapter: levels a CLI cannot honor
are rejected with an explanation of what to use instead — never
silently ignored.

### `orkestra agents models`

What you can pass to `--model` per agent (queries `agy models` live;
shows documented aliases elsewhere).

### `orkestra agents probe [--live]`

Run bounded capability probes (respecting `probes.*` config; `--live`
forces spending even with cached results) and print the evidence-based
capability matrix with scores, confidence, and evidence counts.

## Planning and execution

### `orkestra analyze [--spec FILE] [--offline]`

Director analysis of the specification: summary, assumptions, risks,
capability demands. Creates no run, spends one director call (or none
with `--offline`).

### `orkestra plan [--spec FILE] [--offline]`

Prepare a run without executing: inventory → analysis → probes → plan →
challenges by other agents → validated final plan. Prints the task
table; the prepared run executes later with `orkestra run`.

### `orkestra run [--spec FILE] [--offline] [--watch]`

Execute the latest prepared run, or prepare-and-execute in one go.
Streams events with a per-task progress/cost line; `--watch` attaches the live TUI while executing (needs the `[tui]` extra and a real terminal). Ends in `complete` (exit 0), `waiting on decision`
(exit 2), `cancelled` (exit 3), or failure (exit 1). On success it
summarizes outcomes and points to `orkestra review` / `orkestra accept`.

### `orkestra review [--run ID] [--full]`

What a run built, in plain language: status, tasks finished,
verification and independent-review outcomes, the starting point,
commits and file statistics (`--full` for the whole patch). Incomplete
runs are clearly flagged as partial.

### `orkestra accept [--run ID] [--cleanup] [--yes] [--allow-partial]`

Bring a **completed** run's verified result into your current branch.
Shows a preflight summary and asks for confirmation (default **No**;
`--yes` for automation). Refuses: incomplete runs (unless the advanced,
risky `--allow-partial` is given — which warns and still confirms),
dirty working trees, untracked files the result would overwrite, and
`ork/*` checkouts. Conflicts are aborted cleanly with exact next steps.
`--cleanup` tidies internal branches only after a successful acceptance.

### `orkestra diff` / `orkestra merge`

Backward-compatible aliases of `review` / `accept` (same behavior and
rules) for scripts and long-time users.

## Observability

### `orkestra status [--run ID] [--json]`

Task graph state; `--json` emits the full machine-readable report.

### `orkestra logs [--run ID] [--task KEY] [--limit N]`

Redacted event log (agent output, gate results, warnings).

### `orkestra report [--run ID] [--out FILE.md] [--json-out FILE.json] [--save]`

Full run report: agents, analysis, tasks, attempts, decisions, usage,
agent performance ledger. Redacted; suitable as a support bundle.
`--save` writes both markdown and JSON under `.orkestra/reports/`
(git-ignored, no clutter); an explicit `--out` inside the repository
prints a reminder that the file is untracked.

### `orkestra watch [--run ID]`

Live TUI monitor (optional `[tui]` extra: `uv tool install
'orkestra-runtime[tui]'`). Shows the run header, task table, open
decisions, and a streaming event tail over the same state database the
kernel writes — safe to run alongside `orkestra run` in another
terminal. Keys: `p` request pause, `c` request cancel, `q` quit. It
never dispatches work; execution stays with `run`/`resume`.

## Human gates

### `orkestra decisions [--run ID] [--all]`

Open questions with why-blocked, options, consequences, and the
director's recommendation.

### `orkestra approve [DECISION_ID] [--option KEY] [--note TEXT]`

With no arguments and exactly one open decision, shows it (with the plain-language explanation) and prompts, defaulting to the recommendation. Otherwise resolve a decision (e.g. `retry` resets the task's budgets, `skip`
marks it failed, `abort` fails the run). Follow with `orkestra resume`.

## Control

### `orkestra pause [--run ID]`

Ask a running orchestration (any process) to stop dispatching — new
tasks *and* new attempts within a running task. The in-flight agent
subprocess is never killed; its task returns to ready for the resumed
run.

### `orkestra resume [--run ID] [--offline]`

Reconcile state (close dangling attempts, repair worktrees — safe after
crashes, reboots, Ctrl-C) and continue executing. A run interrupted
before planning produced tasks is re-planned from your spec as a fresh
run instead of erroring.

### `orkestra cancel [--run ID]`

Terminate in-flight agent processes and mark the run cancelled.
Completed work remains on the integration branch.

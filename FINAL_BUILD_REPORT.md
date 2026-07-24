# Orkestra — Final Build Report

Date: 2026-07-24. Build executed autonomously per `MASTERPROMPT.md`.

## Executive summary

Orkestra v0.1.0 is a working, tested, documented, open-source local-first
orchestration runtime that coordinates two or more autonomous coding
agents on one software project. A configurable director agent (default:
Claude Code) analyzes the project, measures agents with objective
capability probes, and plans a task DAG with assignments; a deterministic
non-LLM kernel validates every decision, isolates each task in a Git
worktree, runs acceptance commands itself, enforces independent
cross-agent review, and integrates verified results on a dedicated
branch. State is persistent and resumable across crashes.

The system was validated three ways: a 250+-test suite (unit,
integration, 15-scenario fake-agent E2E, CLI); a **live end-to-end
orchestration on a disposable sample project using the real
authenticated Claude Code, Codex CLI, and Antigravity CLI** (including a
verification-gate failure, automatic fallback repair, human-gate
approve/resume, and a cross-vendor structured review approval); and a
bounded dogfood run of Orkestra reviewing its own codebase.

## Final architecture

See `docs/architecture/ARCHITECTURE.md` (diagrams) and
`docs/architecture/adr/` (8 ADRs). In one paragraph: a Typer CLI drives
an asyncio kernel (`orkestra.kernel`) over a SQLite/WAL store with a
linear migration chain; agents integrate via subprocess adapters
normalizing JSON/JSONL streams into a shared event/result contract;
mutable work happens in per-task Git worktrees created from a per-run
integration branch, with hook-disabled argv-only Git execution; a policy
engine gates dispatch, review pairing, diff paths, budgets, and pushes;
the director role is any adapter bound by config, speaking
schema-validated JSON envelopes with bounded repair retries and a
deterministic heuristic fallback; probes and per-task outcomes accumulate
in an evidence ledger from which the capability matrix and assignment
ranking are built.

## Technology stack and why

Python ≥3.12 + uv; Pydantic v2 (versioned contracts); Typer + Rich
(CLI); stdlib sqlite3 in WAL mode with hand-written migrations (ADR-0003
— SQLAlchemy/Alembic rejected as oversized); custom ~100-line DAG
(NetworkX rejected); custom deterministic kernel (LangGraph/
MS Agent Framework/CrewAI/OpenAI Agents SDK rejected — all orchestrate
API calls, not subscription-authenticated CLI subprocesses; ADR-0002);
subprocess CLI adapters (ADR-0004); Apache-2.0 (ADR-0007). Full weighted
decision matrices: `docs/research/TECH_STACK_DECISION.md`.

## Research performed

Eight research documents under `docs/research/` (retrieved 2026-07-24,
with sources): environment inventory with captured CLI output samples;
competitive analysis (LangGraph, MS Agent Framework, CrewAI, OpenAI
Agents SDK, Claude Agent Teams, Ruflo, claude-squad, Vibe Kanban,
Bernstein, zeroshot, OpenHands, et al.); agent integration surfaces for
all four CLIs; Antigravity CLI deep-dive (including reconciliation of
official docs against local verification); licensing/naming review
(PyPI `orkestra` occupied → distribution name `orkestra-runtime`);
provider terms review; threat model (`docs/security/THREAT_MODEL.md`).

Mid-build environment pivot handled: Google retired individual-consumer
OAuth on the legacy Gemini CLI; the Antigravity CLI (`agy` 1.1.6) was
verified live and became the first-party Google adapter, with
`gemini-cli` retained for API-key/Vertex/Enterprise auth.

## Product capabilities (all exercised by tests)

- ≥2 agents, no fixed-three assumptions (tested at 2, 3, and 5 agents).
- Adapters: `claude-code`, `codex-cli`, `antigravity-cli`, `gemini-cli`,
  `fake`, `external` (documented `orkestra-jsonl/1` protocol + contract
  test kit).
- Dynamic evidence-based delegation; director plan challenges by other
  agents; performance ledger feedback; director reassignment after
  failures.
- Task DAG with cycle detection; parallel execution with configurable
  concurrency; bounded retries/backoff/fallbacks; pause/resume/cancel;
  crash reconciliation.
- Git worktree isolation; deterministic commits; diff path policy;
  no-ff integration with conflict recovery; user branches never touched.
- Kernel-run verification gates (agents cannot self-certify);
  independent review with structural implementer≠reviewer enforcement.
- Human gates with persisted decision records and resume workflow.
- Redaction of credential shapes at write time and export time.
- Reports: live status, event logs, markdown/JSON run reports.

## Repository structure

```
src/orkestra/{schemas,store,kernel,adapters,workspace,policy,verify,
              director,capabilities,report,cli}
tests/{unit,adapters,workspace,e2e,cli}
docs/{research,architecture(+adr),security,adapters,development}
examples/{two-agents,three-agents,many-agents}
```

~7,200 lines of source, ~2,500 lines of tests.

## Installation and quickstart

`docs/INSTALL.md`, `docs/QUICKSTART.md`. Short form:
`uv tool install git+https://github.com/andyyaro/orkestra`, then
`orkestra init . && orkestra doctor && orkestra run`.

## Agent integration status

| Agent | Version tested | Status |
|---|---|---|
| Claude Code | 2.1.219 | Live-verified: director role, structured output (`--json-schema`), implement + fix fallback, resume-scoped sessions |
| Codex CLI | 0.144.4 | Live-verified: plan challenges, independent structured reviews (after OpenAI strict-schema transform, found live) |
| Antigravity CLI | 1.1.6 | Live-verified: headless JSON/stream-JSON, implement attempts; known limitation recorded — headless permission policy can silently skip file writes (`docs/research/ANTIGRAVITY_CLI_RESEARCH.md`), which Orkestra's gates catch |
| Gemini CLI | 0.52.0 | Auth-limited by Google's consumer migration: deterministic auth-not-ready detection verified (exit 41); full path available to API-key/Vertex users |
| fake / external | — | Full contract suite + all E2E scenarios |

## Live tests performed (2026-07-24, this machine)

1. One-shot probes of each CLI's real output shapes (samples committed
   under `docs/research/samples/`).
2. Full orchestration of a disposable sample project (`greet.py` +
   tests + docs) with claude (director) + codex + antigravity: real
   analysis, 8 live capability probes (then cached), plan with 2 live
   challenges, implement → **verification-gate failure caught silently
   non-writing agent** → fallback repair by Claude → gate pass →
   **independent Codex review approved (structured verdict)** →
   integration; human gate exercised (approve retry → resume);
   final state `complete`; integration branch contained exactly the
   specified artifacts. Evidence:
   `docs/development/evidence/LIVE_SMOKE_REPORT.md`.
3. Live-run defects found and fixed during smoke iterations: dirty-repo
   fail-fast before quota spend; orphaned PLANNING runs; prose
   acceptance commands (director prompt + VerificationError human
   gate); pipeline-crash task stranding; codex strict-schema rejection;
   agy empty review response (two-round review candidates).
4. Dogfood: bounded self-review run on Orkestra's own repository
   (see below).

## Test counts and commands

- `uv run pytest` — 253 tests passing (unit, integration/workspace with
  real git, adapters incl. contract suite, 15 E2E orchestration
  scenarios, CLI via Typer runner).
- Coverage: 81–82% overall (`--cov=orkestra`), CI floor 80%; kernel,
  store, policy, and workspace modules 83–100%.
- Static analysis: `ruff check` clean (security rules enabled);
  `mypy --strict` clean over 56 source files; `bandit` 0 findings
  (3 reviewed nosec annotations with justifications).
- Supply chain: `pip-audit` no known vulnerabilities; `uv.lock`
  committed; GitHub Actions least-privilege with gitleaks secret scan.
- Clean-environment install: wheel built (`uv build`), installed into a
  fresh venv, `orkestra --version/init/doctor` plus a **full offline
  orchestration run** executed successfully from the installed package.

## Docker results

Docker daemon verified running (client/server 29.6.1). No container
image is shipped in v0.1; the `policy.sandbox = "docker"` option is
deliberately refused with an explanatory error (vendor CLIs cannot
authenticate in containers without exposing host credentials, which
Orkestra refuses to do) — roadmap v0.2. Docker presence is reported by
`orkestra doctor` as optional.

## Supported platforms

macOS and Linux (CI: ubuntu + macos, Python 3.12/3.13; developed on
macOS 26.5.1 / Python 3.14). Windows untested (roadmap).

## Git / GitHub

- Repository: https://github.com/andyyaro/orkestra (public)
- Default branch: `main`
- Release: v0.1.0 — <!-- RELEASE_URL -->
- History note: pre-publication history was rewritten once to purge a
  fake-but-scanner-triggering test token; no real secret ever existed.

## Global tools installed during the build

Recorded in `docs/development/ENVIRONMENT_CHANGES.md`: Gemini CLI 0.52.0
(npm global; reversible), Docker Desktop launched (no config change).
The Antigravity CLI was installed and authenticated by the user
mid-build.

## Known limitations

- Antigravity headless write-reliability caveat (above); its
  `--output-format` flag is undocumented upstream and may drift (adapter
  has plain-text fallback + feature detection).
- Gemini CLI adapter requires non-consumer auth (Google policy).
- Sustained multi-agent throughput draws on the user's own plan limits;
  "ordinary usage" boundaries are provider-defined (see
  `docs/PROVIDERS.md`, including the Antigravity ToS gray area, which is
  disclosed to users in `doctor` output).
- Docker sandboxing, TUI, Windows, quota-aware scheduling, session
  reuse across tasks: `ROADMAP.md`.

## Reproduction

```bash
git clone https://github.com/andyyaro/orkestra && cd orkestra
uv sync
uv run pytest                      # full suite
uv run ruff check . && uv run mypy && uv run bandit -c pyproject.toml -r src
uv build                           # wheel
# live demo (needs ≥2 authenticated agent CLIs):
mkdir /tmp/demo && cd /tmp/demo && orkestra init . && orkestra doctor
$EDITOR SPEC.md && git add -A && git commit -m spec && orkestra run
```

## Completion criteria

<!-- COMPLETION_STATEMENT -->

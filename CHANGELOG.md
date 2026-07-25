# Changelog

All notable changes to Orkestra are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor versions may contain breaking changes, announced here).

## [Unreleased]

## [0.5.0] - 2026-07-25

Correction release driven by the third fleet test — the first run with
real multi-agent orchestration (report:
`docs/development/FLEET_TEST_REPORT_v0.4.5_REAL_AGENTS.md`). Real agents
exposed a verification pipeline that did not match the product's claims.

### Changed (breaking semantics)
- **Your `[verify]` commands are now always the authoritative gate.**
  Previously a plan-generated `acceptance` list *replaced* them. Now
  plan-proposed entries run only *in addition*, and only when they
  validate as runnable commands (plain argv, no shell/prose syntax,
  executable resolvable); invalid entries are dropped with a warning
  instead of being executed. Runs that relied on director-invented gates
  will now also run the project's own commands.
- `orkestra run` exits 3 when a run ends cancelled (was 0 in some paths).

### Fixed
- A `[verify]` command that cannot start is caught in pre-flight, before
  any agent is dispatched — no more infinite retry loops replaying full
  agent work against a deterministically broken gate. The blocked-task
  explanation now says retrying without fixing the config will fail
  identically, and names the real source of the command.
- Verification failures capture the failing command's stdout/stderr into
  the event log *and* into the repairing agent's fix context (previously
  neither the user nor the agent could see why work was rejected).
- `orkestra resume` recovers a run interrupted before planning finished
  by re-planning from the spec (previously errored "run has no tasks",
  contradicting README/FAQ/TROUBLESHOOTING).
- Usage accounting now covers director analysis, planning, plan
  challenges and capability probes, plus cache-read and cache-creation
  input tokens (new `usage_log.cached_input_tokens` column). Report gains
  a totals row, a cached-input column, 4-decimal costs, and a caveat that
  cost covers only agents that report it.
- `orkestra pause` stops new attempts inside a running task, not just new
  tasks; the in-flight subprocess is never killed.
- Report task table shows Attempts / Reviews run / Rejections derived
  from attempt rows, so a human "retry" no longer erases the history;
  per-attempt `session_id` is exposed in the JSON report.
- A review skipped because a task produced no changes is announced
  explicitly instead of looking like an approval.
- Commits exclude build artifacts (`__pycache__`, `*.pyc`,
  `node_modules`, `.pytest_cache`) that agent test runs generate.
- Claude Code permission stalls in headless runs are detected and
  surfaced as a warning (documented in TROUBLESHOOTING).
- Director analysis in reports no longer leaks tool-call scaffolding, and
  assumptions are shown; long text truncates at a word boundary.
- `[agent]` attribution in commit subjects and streamed events survives
  Rich markup; streamed events are attributed to the acting agent.
- `orkestra status` shows run timing and a "still preparing" hint during
  analysis/probing/planning; `accept` mentions `--cleanup` and describes
  the working tree precisely.

### Documentation
- Full staleness audit: verification-authority model documented across
  CONCEPTS, CONFIGURATION, SECURITY_MODEL, THREAT_MODEL, ARCHITECTURE and
  README; resume/pause/usage/report behavior corrected in CLI, FAQ,
  QUICKSTART, TROUBLESHOOTING; INSTALL temp-file claim and dead link
  fixed; PROVIDERS Codex credential claim corrected; AUTHORING autonomy
  mapping corrected; PROTOCOL usage shape updated.

## [0.4.5] - 2026-07-25

Fixes for the second simulated-user fleet test of 0.4.4
(report: docs/development/FLEET_TEST_REPORT_v0.4.4.md).

### Fixed
- `orkestra start --agents ...` with a recognized-but-not-signed-in
  agent now refuses BEFORE creating the repository/.gitignore — every
  `--agents` failure leaves the directory untouched; an empty
  `--agents ""` is rejected instead of silently ignored.
- The nested-project guard now covers every command: `status`, `run`,
  `doctor`, etc. refuse to operate on a stray `.orkestra/` inside a
  subdirectory of another repository.
- Practice-mode honesty completed: the completion headline now says
  "Practice run complete" (no more "verified result" contradiction),
  real runs say "verified" only when verify commands actually ran, and
  the accept confirmation shows the practice notice.
- `report --out` into a missing directory creates it instead of
  crashing; report's Agents section is populated for demo projects;
  `--save`'s interplay with explicit paths is documented in --help.
- `orkestra run` exits 3 on a cancelled run (was 0); the completion
  summary always describes the run this process executed, not the
  newest run (parallel-invocation mix-up).
- Config validation errors now read "must be one of ..." (no pydantic
  phrasing); the generated config's effort comment states the real
  per-adapter support instead of contradicting the docs.
- `accept` detects untracked-file collisions case-insensitively on
  case-insensitive filesystems and aborts cleanly (with
  `git merge --abort`) on unexpected merge errors.
- Non-ASCII project directory names are slugified into valid config
  names; a read-only `.orkestra/` fails with a clean message; `doctor`
  without a project checks the environment instead of hard-failing.

### Added
- Generated `.gitignore` seeds language build artifacts
  (`__pycache__/`, `*.pyc` for Python projects; `node_modules/` for
  Node) so agent test runs can't commit binary noise.

## [0.4.4] - 2026-07-25

### Fixed
- `orkestra start` and `orkestra init` refuse to set up a project in a
  subdirectory of an existing Git repository (git would resolve every
  command to the parent repo); clear guidance, zero mutation.
- `--agents` is validated before any file or repository mutation — a bad
  value no longer leaves a half-initialized directory.
- Documentation staleness sweep (full audit of every doc file): restored
  the missing 0.4.2/0.4.3 changelog entries; refreshed BUILD_STATUS,
  README test count, SECURITY.md supported versions; corrected
  CONTRIBUTING's contract-test command, THREAT_MODEL's elevated-mode
  flags and hooksPath detail, ARCHITECTURE's autonomy config key, error
  taxonomy, and adapter diagram; documented the nested-repo guard in
  CLI.md and TROUBLESHOOTING; QUICKSTART dirty-repo wording made
  precise; PROTOCOL.md brief example now includes `effort`.

## [0.4.3] - 2026-07-25

### Added
- `orkestra start --agents claude,codex`: restrict setup to the named
  agents instead of enabling every signed-in CLI (aliases: claude,
  codex, antigravity/agy, gemini; at least two required; an agent that
  isn't signed in stops setup with plain guidance — never a silent
  fallback to practice mode).
- `orkestra report --save`: writes markdown + JSON under
  `.orkestra/reports/` (git-ignored).

### Fixed
- `report --out` into the repository now notes the file is untracked
  and points at `--save`.
- Practice runs are honest: run completion and `orkestra review` state
  that the built-in practice agents produce placeholder files and do
  not implement SPEC.md.

## [0.4.2] - 2026-07-25

### Fixed
- Interactive `orkestra start`: blank spec answers explain themselves;
  input ending mid-wizard fails with clear guidance instead of a bare
  "Aborted."
- `run`/`review`/`accept` no longer claim verification "passed" when no
  test commands are configured.
- `orkestra accept` re-run on an already-accepted run is a friendly
  no-op instead of a duplicate success or a raw traceback; a results
  branch deleted without acceptance gets a plain error; missing-terminal
  confirmation now suggests `--yes`.
- `--preset custom --non-interactive` is rejected with an explanation
  (was silently balanced).
- Rich markup no longer eats `[verify]`/`[tui]` from messages and help.
- Unknown `--run` ids error cleanly in status/report/logs/review/cancel;
  `pause`/`cancel` refuse on finished runs instead of reporting fake
  success; config validation errors are plain language.
- Docs: untracked files never block runs; full effort scale documented;
  SPEC.md-edit commit hint after start.


## [0.4.1] - 2026-07-25

Corrective follow-up to v0.4.0: git safety, a coherent review→accept
journey, and honest status documents. No kernel or config changes.

### Fixed

- **`orkestra start` (and `init`) can no longer commit pre-existing
  user work.** Repository state is captured before any mutation;
  existing repos with tracked or staged changes stop with plain-language
  guidance (commit or stash) — deterministically in non-interactive
  mode. Setup commits are pathspec-scoped to an explicit allowlist of
  files Orkestra created in that invocation (SPEC.md, .gitignore) and
  verified against the actual commit contents. New-repo-with-files
  setups commit only Orkestra's files and print exact baseline
  guidance instead of auto-running.
- **Partial results can no longer be merged casually.** `accept`/`merge`
  hard-refuse incomplete runs; the advanced `--allow-partial` flag
  explains what's missing and still confirms (unless `--yes`).
- The success message no longer leads with an internal `ork/*` branch
  name; it summarizes outcomes (tasks, verification, review, usage) and
  points to `orkestra review` / `orkestra accept`.
- `BUILD_STATUS.md` rewritten as a trustworthy current-state document;
  `FINAL_BUILD_REPORT.md` labeled as the historical v0.1.0 snapshot;
  stale counts/claims corrected.

### Added

- `orkestra review [--full]`: plain-language run summary — status, task
  counts, verification and independent-review outcomes, commits, file
  stats, and a clear partial-result warning. `orkestra diff` is now an
  alias of it.
- `orkestra accept [--cleanup] [--yes] [--allow-partial]`: preflight
  summary, confirmation defaulting to **No**, working-tree and
  untracked-collision safety, internal-branch refusal, clean conflict
  aborts with next steps, and cleanup only after success.
  `orkestra merge` is now an alias with identical rules.

## [0.4.0] - 2026-07-25

Progressive-disclosure configuration: `orkestra start → run/watch →
review → accept` is now one coherent journey. Nothing in the normal
path requires TOML, branch names, or knowing what a probe is.

### Added

- `orkestra start`: guided setup — Git init, live agent detection,
  presets (**Faster / Balanced / Maximum quality / Custom**), per-agent
  model choice from discovered or documented lists (custom entry under
  Advanced), effort selection only where genuinely supported,
  verification-command confirmation, spec assistance, and an optional
  immediate run. `--non-interactive --preset …` for automation.
  **Practice mode**: with fewer than two signed-in agents, start
  configures built-in fake agents so the full journey works anywhere,
  free.
- Provider-neutral effort `auto | low | medium | high | max`, mapped
  explicitly per adapter (agy `--effort`, codex
  `model_reasoning_effort`) and hard-validated: unsupported levels are
  rejected with a plain-language explanation — never silently ignored.
- Model discovery with provenance: live `agy models` (cached by adapter
  version), documented aliases labeled as such elsewhere, manual entry
  always available; stale values surface as `manual` instead of hiding.
- Multi-profile presets: Maximum quality fields `claude-deep` (opus) +
  `claude-fast` (haiku) alongside codex/antigravity at high effort; the
  director delegates across profiles like any other agents.
- `orkestra models`: friendly settings screen (profile, adapter, model,
  effort, availability, provenance).
- Presets adjust models/effort/probes/concurrency only — deterministic
  verification and independent review are not preferences.

### Compatibility

- v0.2/v0.3 configs load unchanged (covered by migration tests); safe
  defaults are unmoved.

## [0.3.0] - 2026-07-25

The usability release — everything here came out of a serious "is this
too technical?" self-audit.

### Added

- `orkestra demo`: free, zero-quota, full-lifecycle showcase with
  scripted fake agents driving the real kernel (parallel isolated
  tasks, gate checks, a review rejection + repair, integration).
- `orkestra diff` and `orkestra merge [--cleanup]`: inspect and accept
  a run's results without ever typing an `ork/*` branch name.
- `orkestra agents set NAME --model … --effort …` and `orkestra agents
  models`: pick models and reasoning effort per agent without editing
  TOML (comment-preserving writes, validation with rollback). New
  `agents.<name>.effort` wired to `agy --effort` and codex
  `model_reasoning_effort`.
- `orkestra init` now detects your test culture (pytest / npm / cargo /
  go) and pre-fills `[verify]` commands; spec-quality hints warn about
  vague or template SPEC.md files before quota is spent.
- Plain-language explanations on every human gate (cause → meaning →
  suggested next step), shown in `orkestra decisions` and interactive
  approve.
- `orkestra approve` with no arguments: picks the single open decision
  and prompts, defaulting to the recommendation.
- Live progress/cost line during runs (`▸ progress: 2/5 tasks · 41k
  tokens · $0.31`).
- `orkestra run --watch`: attach the live TUI while the run executes.

## [0.2.0] - 2026-07-25

### Added

- `orkestra watch`: live Textual TUI monitor (optional `[tui]` extra) —
  run header, task table, open decisions, streaming event tail, with
  pause/cancel keys; reads the same SQLite store the kernel writes, so
  it runs safely alongside `orkestra run` from another terminal.
- Docker sandbox (ADR-0009): `policy.sandbox = "docker"` now runs
  **external and fake agents** inside hardened containers — network
  none, cap-drop ALL, no-new-privileges, read-only rootfs with tmpfs
  /tmp, memory/CPU/pids limits, non-root host uid, and only the task
  worktree mounted. Per-agent `sandbox_image` config; vendor CLIs are
  still refused with the credential-exposure explanation; `orkestra
  doctor` treats the Docker daemon as a hard check when enabled.
  Verified live with a real container end-to-end (implement → gates →
  review → integrate).
- Quota-aware scheduling: optional per-agent, per-run token budgets
  (`agents.<name>.token_budget`) computed from the kernel's own usage
  ledger — exhausted agents stop receiving new dispatches and fallbacks
  take over; and global per-agent rate-limit cooldowns with exponential
  escalation — when one agent is rate-limited, eligible alternatives
  dispatch immediately instead of the task sleeping through a backoff.
- Agent session reuse on fix cycles: when verification fails or a
  reviewer requests changes, the retry by the same agent in the same
  workspace resumes the agent's prior CLI session (`--resume` /
  `codex exec resume` / `--conversation`) instead of cold-starting —
  cutting quota use on repair loops. Sessions never cross agents or
  workspaces; disable with `policy.session_reuse = false`.
  Live-verified context recall across resumed Claude invocations.

## [0.1.2] - 2026-07-24

### Added

- PyPI publication via Trusted Publishing (GitHub OIDC): new
  `publish-to-pypi.yml` workflow builds, metadata-checks, and smoke-tests
  distributions, then publishes through the protected `pypi` environment
  with manual approval. No API tokens are stored anywhere.
- Orkestra is now installable as `uv tool install orkestra-runtime`
  (or `pip install orkestra-runtime`).

## [0.1.1] - 2026-07-24

### Security

- Redaction hardening, driven directly by Orkestra's own dogfood
  self-review (`docs/development/SELF_REVIEW.md`):
  - New provider patterns: AWS session tokens, GCP `privateKeyData`,
    Azure `AccountKey`/`SharedAccessSignature`/SAS `sig=`, GitLab
    `glpat-`/`glcbt-`, Slack `xapp-`, npm `npm_`/`.npmrc` `_authToken`,
    PyPI `pypi-`, URL userinfo passwords (user/host preserved).
  - Generic credential matcher now covers provider-prefixed and
    quoted-JSON keys (`AWS_SESSION_TOKEN=`, `"password": "..."`, plain
    `token=`, camelCase `apiKey`) while skipping benign values
    (status words, `${VAR}` templates, absolute paths, masked values)
    and no longer over-consumes past commas.
  - New `redact_structure()` recursively redacts sensitive keys in
    structured event data BEFORE JSON serialization; wired into event
    persistence.
  - Table-driven positive/negative regression suite covering every
    verified miss and false positive from the review.

## [0.1.0] - 2026-07-24

### Added

- Deterministic orchestration kernel: persistent SQLite state, task DAG
  with cycle detection, async scheduler with bounded retries, backoff,
  fallback agents, cancellation, pause/resume, and crash recovery.
- Agent adapter layer with first-party adapters for Claude Code, Codex
  CLI, and Gemini CLI; scripted fake adapter; external-command adapter
  protocol (`orkestra-jsonl/1`); adapter contract test kit.
- Git workspace engine: per-task worktree isolation, base-commit
  tracking, hook-disabled Git execution, diff path-policy checks,
  no-ff integration with conflict detection, interrupted-operation
  recovery.
- Director system (default: Claude Code) with schema-validated decision
  envelopes, deterministic heuristic fallback planner, capability
  probes with budgets and caching, weighted capability matrix with
  confidence, agent performance ledger, and dynamic reassignment.
- Policy engine with safe defaults, explicit opt-in elevated modes,
  independent-review enforcement (implementer ≠ reviewer), and
  deterministic verification gates that agents cannot override.
- Human gates: persisted decision records, `orkestra decisions` /
  `orkestra approve`, resume-after-decision workflow.
- CLI: `init`, `doctor`, `agents list|probe`, `analyze`, `plan`, `run`,
  `status`, `logs`, `decisions`, `approve`, `pause`, `resume`, `cancel`,
  `report`.
- Secret redaction for logs, reports, and support bundles.
- Full research corpus, architecture documentation, ADRs, and threat
  model.

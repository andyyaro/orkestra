# Changelog

All notable changes to Orkestra are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor versions may contain breaking changes, announced here).

## [Unreleased]

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

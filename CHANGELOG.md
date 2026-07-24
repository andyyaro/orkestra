# Changelog

All notable changes to Orkestra are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor versions may contain breaking changes, announced here).

## [Unreleased]

### Added

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

# ADR-0004: Agent integration — CLI subprocesses with structured streaming

Date: 2026-07-24 · Status: accepted

## Context

Options per agent: official SDKs, app-server/daemon modes, MCP, or CLI
subprocesses. Constraint: must work with the user's existing
subscription-authenticated CLI installs, without touching credentials.
Evidence: `docs/research/ENVIRONMENT_INVENTORY.md`,
`docs/research/AGENT_INTEGRATION_RESEARCH.md`, `docs/research/samples/`.

## Decision

All first-party adapters spawn the installed CLI as a subprocess in
headless mode with JSON/JSONL output:

- Claude Code: `claude -p --output-format stream-json` (single `result`
  object confirmed locally; stream events for progress).
- Codex: `codex exec --json` (JSONL `thread.*`/`item.*`/`turn.*` events
  confirmed locally; `--output-schema` available for structured finals).
- Gemini: `gemini -p -o stream-json` (auth-not-ready = exit 41 with JSON
  error on stderr, confirmed locally).

The Claude *director* role also uses `claude -p`, with strict JSON
decision envelopes parsed and schema-validated by the kernel.

## Rationale

- Subprocess + official CLI is the only integration that (a) uses each
  provider's official auth flow untouched, (b) inherits each CLI's own
  sandbox/permission system, (c) is uniform across all three vendors,
  and (d) keeps Orkestra dependency-free of vendor SDK churn.
- The Claude Agent SDK wraps the same CLI; adopting it for one agent
  would split the adapter model without adding capability we need.
- Codex `app-server` and Gemini ACP are marked experimental by their
  vendors; unsuitable as v0.1 foundations (revisit on the roadmap).

## Consequences

- Adapters carry version/feature detection and defensive normalization
  (CLI output formats change; contract tests + samples pin expectations).
- Session resumption uses each CLI's resume surface where present.

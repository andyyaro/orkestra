# Orkestra Roadmap

Direction, not commitment. Items move as evidence accumulates.

## v0.2

- Docker sandbox execution mode for agent tasks (worktree mounted into a
  non-root, resource-limited container). Scaffolding exists behind
  `sandbox = "docker"`; needs hardening and CI coverage.
- Textual-based TUI (`orkestra watch`) over the same state store.
- Quota-aware scheduling using recorded usage observations per agent.
- Adapter session reuse across tasks (Claude `--fork-session`, Codex
  `exec resume`) for cheaper multi-turn refinement loops.

## v0.3

- Python entry-point plugin adapters behind an explicit allowlist
  (extends the external-command protocol; see ADR-0006).
- Alternative directors: Codex- and Gemini-led direction, plus a fully
  offline heuristic director mode.
- Windows support (worktree paths, process groups, signal semantics).
- MkDocs Material documentation site.

## Later / exploratory

- MCP-based adapter surface (`codex mcp-server`, Claude MCP) as an
  alternative to subprocess JSONL.
- OpenTelemetry export of runtime events.
- PyPI publication as `orkestra-runtime` (and PEP 541 request for the
  dormant `orkestra` name).
- Multi-repository projects; cross-repo task graphs.
- Cost/quota dashboards from the usage ledger.
- Signed release artifacts and SLSA provenance.

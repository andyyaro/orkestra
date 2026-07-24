# Orkestra Roadmap

Direction, not commitment. Items move as evidence accumulates.

## v0.2

- Docker sandbox execution mode for agent tasks (worktree mounted into a
  non-root, resource-limited container). Scaffolding exists behind
  `sandbox = "docker"`; needs hardening and CI coverage.
- Textual-based TUI (`orkestra watch`) over the same state store.
- Quota-aware scheduling using recorded usage observations per agent.
- ~~Adapter session reuse~~ shipped for fix cycles (post-0.1.2);
  remaining: cross-task session forking (Claude `--fork-session`).

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
- PEP 541 request for the dormant bare `orkestra` PyPI name
  (`orkestra-runtime` is published as of v0.1.2).
- Multi-repository projects; cross-repo task graphs.
- Cost/quota dashboards from the usage ledger.
- Signed release artifacts and SLSA provenance.

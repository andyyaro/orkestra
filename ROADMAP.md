# Orkestra Roadmap

Direction, not commitment. Items move as evidence accumulates.

## v0.2

- ~~Docker sandbox~~ shipped post-0.1.2 for external/fake agents
  (ADR-0009); remaining: vendor-CLI containerization pending
  vendor-supported container auth, and cidfile-based teardown of
  daemon-side strays on hard kills.
- Textual-based TUI (`orkestra watch`) over the same state store.
- ~~Quota-aware scheduling~~ shipped post-0.1.2: per-agent token
  budgets and global rate-limit cooldowns with immediate fallback.
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

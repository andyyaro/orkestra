# ADR-0001: Implementation language — Python 3.12+

Date: 2026-07-24 · Status: accepted

## Context

Orkestra is a local-first orchestrator whose hot path is process
supervision, JSONL parsing, Git plumbing, and SQLite I/O — not
compute-bound work. Candidates: Python, TypeScript/Node, Rust, Go
(scored in `docs/research/TECH_STACK_DECISION.md`).

## Decision

Python, requiring 3.12+ (developed on 3.14), packaged with `uv` and
`pyproject.toml`.

## Rationale

- `asyncio` subprocess management, streaming line readers, timeouts, and
  cancellation cover the entire runtime need with stdlib primitives.
- Pydantic gives versioned, validated schemas — the backbone of the
  structured contracts requirement.
- `sqlite3` is stdlib; no runtime service dependencies.
- Typer/Rich give a polished CLI cheaply.
- Testability (pytest + pytest-asyncio) and contributor onboarding are
  best-in-class; the target contributor pool (agent-tool users) skews
  Python.
- Rust/Go would improve startup latency and distribution (single binary)
  at a large cost in iteration speed and schema ergonomics; neither
  matters much for a tool whose latency is dominated by LLM agents.
- TypeScript was the strongest alternative (agent CLIs are Node-based)
  but loses on schema validation ergonomics, SQLite stdlib, and the
  scientific/automation ecosystem for future analysis features.

## Consequences

- Distribution via PyPI/`uv tool install`; no single-binary story in v0.1
  (roadmap: PyInstaller/shiv evaluation).
- Strict typing enforced with mypy `--strict` to offset dynamic-language
  risk.

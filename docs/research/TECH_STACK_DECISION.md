# Technology Stack Decision

Date: 2026-07-24. Evidence: `ENVIRONMENT_INVENTORY.md`, `samples/`,
`COMPETITIVE_ANALYSIS.md`, `AGENT_INTEGRATION_RESEARCH.md`,
`LICENSING_AND_NAMING_REVIEW.md`, `TERMS_AND_AUTHENTICATION_REVIEW.md`.

## Weighted criteria

Weights (1–5) reflect the product's non-negotiables: it must reliably
drive subscription-authenticated CLI subprocesses locally with
deterministic control, survive crashes, and be maintainable by a small
open-source community. Portability and performance matter but are not
where this product wins or loses.

| # | Criterion | Weight | Why this weight |
|---|---|---|---|
| 1 | Compatibility with subscription-authenticated CLIs | 5 | Core premise; anything that can't spawn/stream the installed CLIs is disqualified |
| 2 | Local-first operation | 5 | Core premise |
| 3 | Deterministic control | 5 | Core differentiator |
| 4 | Extensibility to arbitrary agents | 4 | ≥2 agents, N agents, third-party adapters |
| 5 | Structured streaming | 4 | JSONL normalization is the adapter backbone |
| 6 | Process cancellation | 4 | Safety requirement |
| 7 | Git worktree support | 4 | Isolation model |
| 8 | Crash recovery | 5 | Resumability is a completion criterion |
| 9 | Testability | 5 | Evidence-over-self-report culture |
| 10 | Security | 5 | §9 requirements |
| 11 | Maintainability | 4 | Solo/small-team OSS reality |
| 12 | Cross-platform portability | 3 | macOS/Linux now, Windows later |
| 13 | Dependency maturity | 4 | Supply-chain posture |
| 14 | Licensing | 3 | Permissive ecosystem |
| 15 | Performance | 2 | Latency dominated by LLM agents |
| 16 | Developer onboarding | 3 | Contributor growth |
| 17 | Long-term OSS sustainability | 4 | Avoid framework churn |

## Decision 1 - Implementation language

Scores 1–5 per criterion; total = Σ(weight × score), max 345.

| Criterion (weight) | Python | TypeScript/Node | Rust | Go |
|---|---|---|---|---|
| Subscription CLIs (5) | 5 | 5 | 5 | 5 |
| Local-first (5) | 5 | 5 | 5 | 5 |
| Deterministic control (5) | 5 | 5 | 5 | 5 |
| Extensibility (4) | 5 | 4 | 3 | 3 |
| Structured streaming (4) | 5 | 5 | 4 | 4 |
| Cancellation (4) | 4 | 4 | 5 | 5 |
| Worktrees (4) | 5 | 5 | 5 | 5 |
| Crash recovery (5) | 5 | 4 | 5 | 5 |
| Testability (5) | 5 | 4 | 4 | 4 |
| Security (5) | 4 | 3 | 5 | 4 |
| Maintainability (4) | 5 | 4 | 3 | 4 |
| Portability (3) | 4 | 4 | 5 | 5 |
| Dependency maturity (4) | 5 | 4 | 4 | 4 |
| Licensing (3) | 5 | 5 | 5 | 5 |
| Performance (2) | 3 | 3 | 5 | 5 |
| Onboarding (3) | 5 | 4 | 2 | 3 |
| OSS sustainability (4) | 5 | 4 | 3 | 4 |
| **Total (max 345)** | **326** | **295** | **294** | **300** |

**Python wins** on schema ergonomics (Pydantic), stdlib SQLite, pytest
culture, and contributor pool; it concedes only startup latency and
single-binary distribution, both minor for an agent-bound tool
(ADR-0001). TypeScript was second (vendor CLIs are Node) but loses on
validation ergonomics and stdlib persistence; Go/Rust trade too much
iteration speed for performance this product doesn't need.

## Decision 2 - Orchestration core

| Criterion (weight) | Custom kernel | LangGraph | MS Agent Framework | CrewAI | OpenAI Agents SDK |
|---|---|---|---|---|---|
| Subscription CLIs (5) | 5 | 1 | 1 | 1 | 1 |
| Deterministic control (5) | 5 | 3 | 4 | 2 | 2 |
| Extensibility to CLI agents (4) | 5 | 2 | 2 | 2 | 2 |
| Crash recovery fit (5) | 5 | 4 | 3 | 2 | 2 |
| Testability (5) | 5 | 3 | 3 | 2 | 3 |
| Security (5) | 5 | 3 | 3 | 2 | 3 |
| Maintainability (4) | 4 | 3 | 3 | 3 | 3 |
| Dependency maturity (4) | 5 | 4 | 3 | 3 | 4 |
| OSS sustainability (4) | 5 | 4 | 3 | 3 | 3 |
| **Total (max 205)** | **200** | **121** | **116** | **89** | **99** |

All frameworks orchestrate LLM **API calls**; none provide process
supervision, worktree isolation, or deterministic gates for CLI agents.
**Custom kernel** (ADR-0002). This is not "not-invented-here": the
frameworks' value (model clients, tool loops) sits entirely inside the
agent CLIs we spawn.

## Decision 3 - Agent integration method

CLI subprocess with structured streaming for all three agents
(ADR-0004). SDK/daemon alternatives per agent were evaluated in
`AGENT_INTEGRATION_RESEARCH.md`: the Claude Agent SDK wraps the same
CLI; Codex app-server and Gemini ACP are vendor-marked experimental.
Subprocess is the only uniform, officially supported, auth-untouched
surface. Verified locally with captured output samples.

## Decision 4 - Persistence

SQLite (stdlib, WAL) + versioned JSON payloads + linear SQL migrations;
SQLAlchemy/Alembic rejected as oversized for ~15 tables (ADR-0003).
Event log is an append-only table in the same database - a separate
event-log file adds a consistency boundary with no benefit at this
scale.

## Decision 5 - Task DAG

Custom in-memory DAG (dict adjacency + Kahn's algorithm for cycle
detection and topological ready-frontier computation), persisted
relationally. NetworkX rejected: a full graph-theory library for one
algorithm is unjustified dependency surface.

## Final stack (deviations from the provisional hypothesis noted)

| Component | Choice | vs. hypothesis |
|---|---|---|
| Language | Python ≥3.12 (dev on 3.14) | kept (3.13→3.12 floor widens compatibility) |
| Packaging | uv + pyproject.toml, distribution `orkestra-runtime` | kept |
| Async | stdlib asyncio | kept (AnyIO rejected: single backend, no trio need) |
| Schemas | Pydantic v2 | kept |
| CLI | Typer + Rich | kept |
| TUI | none in v0.1 | **deferred** (roadmap) - correctness first |
| Store | stdlib sqlite3, WAL | **simplified** (SQLAlchemy 2 + Alembic dropped, ADR-0003) |
| DAG | custom (~100 lines) | **simplified** (NetworkX dropped) |
| Adapters | JSON/JSONL subprocess | kept |
| Isolation | Git worktrees; Docker opt-in | kept |
| Tests | pytest + pytest-asyncio + coverage | kept |
| Lint/format | Ruff (lint + format) | kept |
| Types | mypy --strict | chosen over pyright (pure-Python toolchain, no Node in CI critical path) |
| Security | Bandit + pip-audit + gitleaks in CI | kept (+secret scan) |
| Logging | stdlib logging with structured JSON handler | **simplified** (structlog dropped - one fewer dependency, same output) |
| Docs | Markdown in-repo (docs/) | **simplified** (MkDocs site deferred to roadmap) |
| CI | GitHub Actions (pinned, least-privilege) | kept |
| Telemetry | none (OpenTelemetry deferred) | **deferred** |

## Known uncertainties and mitigations

- **CLI output formats drift** with vendor releases → version detection
  in adapters, golden samples in `docs/research/samples/`, defensive
  normalization, contract tests.
- **Gemini live validation** blocked by interactive auth on this
  machine → adapter ships with deterministic auth-not-ready detection
  (exit 41 + JSON stderr, verified); live path exercised when a user
  authenticates.
- **Quota opacity** → usage metadata recorded when CLIs expose it;
  scheduling treats it as advisory.

## Implementation sequence

Phases 2–10 as specified: foundation → kernel/persistence → adapters →
git engine → director/capabilities → CLI → policy/gates → E2E/dogfood →
docs/release.

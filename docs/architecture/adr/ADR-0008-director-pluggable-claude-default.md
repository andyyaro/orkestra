# ADR-0008: Director - protocol-based role, Claude Code default

Date: 2026-07-24 · Status: accepted

## Context

v1 defaults to Claude Code as director, but the core must not be
inseparably coupled to Claude, and a future alternative director must be
possible.

## Decision

The director is a **role bound to any configured agent adapter**, not a
hard-coded integration. `DirectorProtocol` defines the required
exchanges (analyze, demand profile, probe design, plan, challenge
response, arbitration, reassignment), each a schema-validated JSON
envelope. `director = "claude-code"` is the config default; any adapter
whose feature flags include `structured_director` can be selected,
including the fake adapter (used by tests and offline mode).

## Rationale

- Keeps the "Claude as director" v1 promise while making the coupling a
  configuration default rather than an architectural fact.
- The fake director makes the entire orchestration loop testable without
  quota.

## Consequences

- Director prompts are maintained as versioned templates; responses are
  validated and re-requested on schema failure (bounded retries), with
  kernel-side fallbacks (e.g., deterministic heuristic plan) when the
  director is unavailable and policy permits.

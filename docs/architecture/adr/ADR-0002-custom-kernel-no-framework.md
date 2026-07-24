# ADR-0002: Orchestration core — custom deterministic kernel, no agent framework

Date: 2026-07-24 · Status: accepted

## Context

Candidates: LangGraph, Microsoft Agent Framework (AutoGen/Semantic
Kernel successor), CrewAI, OpenAI Agents SDK, or a custom kernel.
Scored in `docs/research/TECH_STACK_DECISION.md`; landscape in
`docs/research/COMPETITIVE_ANALYSIS.md`.

## Decision

Build a custom deterministic kernel (~asyncio scheduler + SQLite state
machine + policy engine). No LLM-agent framework dependency.

## Rationale

- Every framework in the candidate set orchestrates **LLM API calls**;
  Orkestra orchestrates **subprocess CLI agents** with their own auth,
  sandboxes, and session models. The frameworks' core abstractions
  (model clients, tool schemas, handoffs) don't apply, while the parts
  Orkestra needs (process supervision, worktrees, deterministic gates,
  transactional resume) aren't provided by any of them.
- The product's differentiator is precisely that the control plane is
  *not* an LLM framework: schema-validated director decisions enter a
  kernel that enforces policy. Adopting a framework would blur the
  boundary the architecture depends on.
- LangGraph's checkpointing is the one tempting feature; SQLite +
  idempotent transitions covers it with less dependency surface and
  full auditability.

## Consequences

- We own scheduler/retry/resume correctness — mitigated by heavy unit
  and crash-recovery tests (kernel is the best-covered module).
- No framework lock-in; adapters and kernel evolve with vendor CLIs.

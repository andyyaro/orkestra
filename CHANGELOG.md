# Changelog

All notable changes to Orkestra are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor versions may contain breaking changes, announced here).

## [Unreleased]

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

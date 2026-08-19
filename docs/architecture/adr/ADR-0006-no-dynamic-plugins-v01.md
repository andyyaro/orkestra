# ADR-0006: Extensibility - declarative adapter manifests, no dynamic code loading in v0.1

Date: 2026-07-24 · Status: accepted

## Context

Third-party adapters are required, but silently executing discovered
code is a supply-chain hazard (threat T7).

## Decision

v0.1 supports third-party agents as **external commands** declared
explicitly in project config with a manifest (name, command, args
template, protocol: `orkestra-jsonl/1`). Orkestra never imports plugin
Python code and never auto-discovers executables. The fake adapter and
the adapter test kit implement and verify the same protocol.

## Rationale

- An external-command protocol is language-agnostic (an adapter can be
  a shell script) and inherits the same process supervision, timeouts,
  and normalization as first-party adapters.
- Entry-point-based Python plugins can come later behind an explicit
  allowlist without breaking this contract.

## Consequences

- Third-party adapters communicate via the documented JSONL protocol
  (`docs/adapters/PROTOCOL.md`); the test kit is the compliance suite.

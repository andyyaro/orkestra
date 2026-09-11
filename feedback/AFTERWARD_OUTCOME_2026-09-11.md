# Outcome — Orkestra built (and reviewed) a real component (Afterward)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 · **Run:** `run_8473a96e`
**Roster:** claude (claude-code 2.1.269) + codex (codex-cli 0.149.0), both `adapter default` / `auto`. No antigravity/gemini.

This closes the loop on the two earlier dogfooding reports: I actually shipped a component Orkestra built.

## What Orkestra delivered
A dependency-free **PII-redaction module** for Afterward (`redact_ssn` / `redact_text` / `redact_profile`), now
integrated into the product and scrubbing every live-trace event. Process:

- **Offline heuristic plan ($0):** 3-task DAG (implement/test/document) with cross-agent reviewers + an integration branch.
- **Implement (claude, isolated worktree):** a well-documented module + pytest suite; main branch untouched.
- **Verify (pytest gate):** deterministic, ran green before review.
- **Review (codex, adversarial):** the headline result.

## The headline: cross-agent review caught real bugs the author missed
Codex did **not** rubber-stamp. Across two review cycles it found two genuine PII-leak defects in claude's drafts:

1. **severity high** — `_SSN_RE` incorrectly excluded a boundary case.
2. **severity medium** — `_EMAIL_RE` was incomplete for valid addresses: it proved with a concrete input that
   `redact_text('"jane.doe"@example.com')` returned the address **unchanged** (a real PII leak), after probing RFC-5322
   oddities (quoted local parts, IP-literal domains) that the spec never mentioned.

This is the single best argument for Orkestra's thesis: **a different-vendor reviewer catches what the author ships.**
A single-agent pipeline would have leaked PII here. Worth featuring this exact example in the README/marketing — it's
concrete, verifiable, and security-relevant.

## Honest caveats from this run (already detailed in the other two reports)
- The run needed operator intervention to get `pytest` on PATH (verify-command/venv trap) before it flowed.
- On `auto` effort, the codex review loop is deep and slow; the run hit my 15-min wrapper timeout mid-fix-cycle, so I
  finished the last codex-requested fix by hand and integrated. (Not an Orkestra fault — my timeout — but pinning
  `--effort` or a per-run wall-clock budget would help unattended runs.)

## Net
The engine did exactly what it promises: planned, dispatched to isolated worktrees, gated on tests, and ran a real
adversarial cross-review that improved the result. The friction is all onboarding/DX (see the other reports); the core
value proposition demonstrably works. Afterward now ships code Orkestra built and Codex hardened.

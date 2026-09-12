# Outcome — Orkestra built (and reviewed) a real component (Afterward)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 · **Run:** `run_8473a96e`
**Roster:** claude (claude-code 2.1.269) + codex (codex-cli 0.149.0), both `adapter default` / `auto`. No antigravity/gemini.

This closes the loop on the two earlier notes: I actually shipped a component Orkestra built. Recording what happened,
not prescribing anything.

## What Orkestra delivered
A dependency-free **PII-redaction module** for Afterward (`redact_ssn` / `redact_text` / `redact_profile`), which I then
integrated into the product. The sequence:

- **Offline heuristic plan ($0):** a 3-task DAG (implement/test/document) with cross-agent reviewers + an integration branch.
- **Implement (claude, isolated worktree):** a well-documented module + pytest suite; my main branch untouched.
- **Verify (pytest gate):** deterministic, ran green before review.
- **Review (codex, adversarial):** the part worth recording in detail, below.

## The thing that stood out: cross-agent review caught real bugs the author missed
Codex did **not** rubber-stamp. Across two review cycles it found two genuine PII-leak defects in claude's drafts:

1. **severity high** — `_SSN_RE` incorrectly excluded a boundary case.
2. **severity medium** — `_EMAIL_RE` was incomplete for valid addresses: it proved, with a concrete failing input, that
   `redact_text('"jane.doe"@example.com')` returned the address **unchanged** (a real leak), after probing RFC-5322
   oddities (quoted local parts, IP-literal domains) the spec never mentioned.

A single-agent pipeline would have shipped that leak. Seeing a different-vendor reviewer catch what the author produced
was the most memorable moment of the whole run — concrete and verifiable, not a demo contrivance.

## Honest caveats from this run (detailed in the other two notes)
- The run needed my intervention to get `pytest` onto PATH (the verify-command / venv situation) before it flowed.
- On `auto` effort the codex review loop ran deep and slow; the run hit my own 15-minute wrapper timeout mid-fix-cycle,
  so I finished the last codex-requested fix by hand and integrated. That timeout was mine, not Orkestra's.

## Net impression
The engine did what it promises: it planned, dispatched to isolated worktrees, gated on tests, and ran a real
adversarial cross-review that measurably improved the result. The friction I hit was all at the verify boundary (see the
other notes). Afterward now ships code Orkestra built and Codex hardened.

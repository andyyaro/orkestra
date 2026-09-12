# Dogfooding notes — running Orkestra 0.5.5 for real (Afterward, Option A)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 · **Context:** used `orkestra run` to actually build a real
Afterward component (`afterward_redact`, a PII-redaction module) with the **claude-code adapter** — director planned
offline, Claude Code implemented in an isolated worktree, `pytest` as the gate, Codex as reviewer. This is a **runtime**
account of what happened; the earlier note covered the programmatic API.

These are observations from the run, not a change list. Everything below is from real runs of `run_f0f3e323`; what to
do about any of it is the maintainer's call.

## What worked well
- `orkestra init` correctly auto-detected the test culture (`pytest -q`) and all four agent CLIs (claude, codex,
  antigravity, gemini).
- `orkestra plan --offline` produced a sensible 3-task plan (implement→claude, test→codex, document→antigravity) with
  **cross-agent reviewers** and **plan challenges from codex + antigravity** (both accepted) — genuinely impressive, and $0.
- Isolated git worktrees per task worked exactly as advertised; my main branch was never touched.
- The `waiting_human` → `orkestra decisions` → `orkestra approve` → `orkestra resume` loop is clean and legible. The
  decision text (question + "what this means" + a fix hint) is unusually good.
- The Claude Code agent it drove produced a high-quality module on its own (guarded SSN regex, recursive dict redaction,
  a growing test suite).

## What I observed

### 1. The `claude -p` worker ran with Bash restricted, so it couldn't run its own verify command
The driven Claude Code agent repeatedly logged: *"Bash is restricted here … I can't execute pytest in this
non-interactive session (Bash requires approval)."* It adapted (wrote a `conftest.py`, pinned rootdir) but could never
actually run the tests it was writing — so it was implementing without being able to see its own verification. For a
system whose pitch is "your test commands are the referee," it was striking that the author agent itself was flying blind.

### 2. A project-venv `pytest` silently blocked the run at the verify step
`verify.commands` was `pytest -q`, but pytest lived in a project `.venv` rather than on PATH, so the verify step failed
with *"verification command not found: 'pytest'"* and the run blocked on a human decision. It surprised me because
keeping pytest in a venv is the norm for Python projects, so I hit this immediately without doing anything unusual.

### 3. Editing `.orkestra/config.toml` after a run was created didn't affect that run
I changed `verify.commands` to point at the venv's pytest, approved `retry`, and resumed — but the retry still used the
original `pytest -q`. The run appears to snapshot config at creation time. I lost a cycle before I realized the edit
wasn't being picked up.

### 4. `retry` re-ran the whole agent task even though only the verify command was misconfigured
The implement agent had finished cleanly (`exit=0 status=ok`); the only failure was the verify command not being on PATH
— a setup issue, not a test failure. But the recovery options were `retry` / `skip` / `abort`, and `retry` re-ran the
entire (token-expensive) Claude Code implement task in a fresh worktree, rebuilding work that was already fine.

## Net impression
The engine, the multi-agent plan, the worktree isolation, and the decision loop all felt genuinely good. The friction I
hit was concentrated at the verify boundary — the worker couldn't run the gate, the gate couldn't find its command, a
config edit didn't take on retry, and retry rebuilt good work. Noting it here as lived experience; filed while building
Afterward's PII-redaction component, which Orkestra did in fact build.

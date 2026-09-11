# Dogfooding feedback — running Orkestra 0.5.5 for real (Afterward, Option A)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 · **Context:** used `orkestra run` to actually build a real
Afterward component (`afterward_redact`, a PII-redaction module) with the **claude-code adapter** — director planned
offline, Claude Code implemented in an isolated worktree, `pytest` as the gate. This is a **runtime** report (the earlier
one was about the programmatic API). Everything below is from real runs of `run_f0f3e323`.

## What worked really well
- `orkestra init` correctly auto-detected the test culture (`pytest -q`) and all four agent CLIs (claude, codex,
  antigravity, gemini).
- `orkestra plan --offline` produced a sensible 3-task plan (implement→claude, test→codex, document→antigravity) with
  **cross-agent reviewers** and **plan challenges from codex + antigravity** (both accepted) — genuinely impressive,
  and $0.
- Isolated git worktrees per task worked exactly as advertised; the main branch was never touched.
- The `waiting_human` → `orkestra decisions` → `orkestra approve --option retry` → `orkestra resume` loop is clean and
  legible. The decision text ("what this means" + fix hint) is excellent.
- The Claude Code agent it drove produced a high-quality module (guarded SSN regex, recursive dict redaction, 21 tests)
  entirely on its own.

## Issues found (in priority order)

### 1. The `claude -p` adapter runs with Bash **restricted**, so the worker can't run its own verify command
The driven Claude Code agent repeatedly logged: *"Bash is restricted here … I can't execute pytest in this
non-interactive session (Bash requires approval)."* It adapted (wrote a `conftest.py`, pinned rootdir) but could never
actually run the tests it wrote. This partially undercuts the "your test commands are the referee" story for the claude
adapter specifically — the agent is flying blind on verification. **Ask:** pass `--dangerously-skip-permissions` (or a
scoped `--allowedTools "Bash(pytest*)"`) to the spawned `claude -p`, or document that the claude adapter needs a
permission config so the worker can self-verify.

### 2. `verify.commands` must be PATH-resolvable in a bare checkout — a project venv silently breaks the run
`pytest -q` failed with *"verification command not found: 'pytest'"* because pytest lived in a project `.venv`, not on
PATH. The run blocked on a human decision. This is an easy trap (most Python projects keep pytest in a venv). **Ask:**
either (a) auto-detect a `.venv`/`uv` environment and run verify inside it, (b) support a `verify.python` / `verify.env`
setting, or (c) call this out loudly in `INSTALL.md`/`CONFIGURATION.md` ("verify commands run in a bare checkout — they
must resolve on PATH; a project-venv `pytest` will not").

### 3. Editing `.orkestra/config.toml` after a run is created does **not** affect that run
I fixed `verify.commands` to point at the venv's pytest, approved `retry`, and resumed — but the retry still used the
original `pytest -q`. The run appears to **snapshot** config at plan/creation time. This was surprising and cost a cycle.
**Ask:** document that config is captured per-run, and/or re-read `verify.commands` on `retry`.

### 4. `retry` re-runs the whole agent task from scratch when only the verify command was misconfigured
The implement agent finished cleanly (`exit=0 status=ok`); the ONLY failure was the verify command not being on PATH
(a setup error, not a test failure). But the only recovery options were `retry` / `skip` / `abort`, and `retry` re-ran
the entire (expensive) Claude Code implement task in a fresh worktree — re-spending tokens to rebuild work that was
already fine. **Ask:** when the block is a *verification-setup* error (command-not-found) rather than a failed
assertion, offer a **`re-verify`** option that just re-runs the gate against the existing worktree.

## Net
The engine, the multi-agent plan, the worktree isolation, and the decision loop are genuinely good. The friction is all
at the verify boundary: the worker can't run the gate (perms), the gate can't find its command (venv/PATH), config edits
don't take on retry, and retry over-rebuilds. Fixing #1 and #2 would make the claude-adapter happy-path work end to end
without a human decision. Filed while building Afterward's PII-redaction component — which Orkestra did, in fact, build.

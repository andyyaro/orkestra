# Orkestra - Session Handoff / Context Transfer

**Originally written 2026-07-26 (v0.5.3 session). Updated 2026-09-08 after a
session that landed four PRs. Read this first when resuming work in
`~/Downloads/Orkestra`.**

## Session of 2026-09-08 (most recent)

Between the v0.5.3 session and this one, on **2026-08-19**, the maintainer did a
cleanup pass across both this repo and Provalume. Three consequences that
invalidate parts of the older text below:

| What changed | Detail |
|---|---|
| History rewritten | `Co-Authored-By` trailers stripped from all 84 commits, all tags re-pointed. Trees are byte-identical; only SHAs changed. **Any clone from before that date has no common ancestor with `origin/main`.** Re-sync with `git fetch --tags --force` then `git reset --hard origin/main`. |
| PR #6 closed | `provalume-memory-integration` was **closed unmerged** 2026-08-19T21:50Z. Section 5 below is history, not a live thread. |
| Style sweep | Em dashes replaced with hyphens across docs and source; README status badges added. **Write commit messages without `Co-Authored-By` and without em dashes.** |

What this session did, all merged to `main`:

| PR | What |
|---|---|
| #12 | Routed all 142 CLI exit-code assertions through `tests/cli/asserts.py`. Zero raw `.exit_code` asserts remain. |
| #13 | Command failures lead with the reason, not the argv; `cli/text.py` `clip()` marks truncation. |
| #14 | `_failure_reason()` picks git's `fatal:` line rather than its progress narration. |
| #15 | **The macOS flake, fixed.** `WorkspaceManager._worktree_admin` serializes worktree administration. |

**The flake chain, which is the story worth keeping.** Three CI failures had been
reported only as `assert 2 == 0`. #12 made the assertion name it: exit 2 is
`RunState.WAITING_HUMAN`, so the run had not crashed, a task had blocked. The run
narration then stopped one character short of the cause, because `_print_event`
clips at 220 characters and the prefix plus a worktree argv is 219 of them. #13
and #14 made the reason survive that clip. Only then did the real error appear,
in a stress reproducer at 1 run in 200:

```
git worktree add failed (exit 128): fatal: could not open
'.git/worktrees/integrate-run_548419e0-merge-37b1b2/locked' for writing:
No such file or directory
```

`git worktree add` builds `.git/worktrees/<name>/` in steps and `git worktree
prune` deletes any entry without a gitdir yet, so a prune landing inside another
add's window kills it. Reproduced outside Orkestra at about 2.5% (6 of 240). Two
earlier hypotheses were tested and **rejected** first: plain concurrent adds do
not fail (0 of 60, 0 of 320 detached), and deleting a sibling branch from the
same ref directory during an add does not fail (0 of 120).

Suite is now **486 passed, 1 skipped**. `main` is 6 commits ahead of the v0.5.3
tag and **unreleased**: badges, the em dash sweep, and the four PRs above.

### THE OPEN FINDING: the gate does not necessarily read the tree it names

A 39-agent research workflow asked what would make Orkestra genuinely novel. Its
answer matters less than what it turned up on the way, which was **independently
reproduced twice and is a live defect in the central product claim**.

Orkestra runs the gate with `cwd` set to the task worktree and assumes that makes
the verdict a statement about that worktree. For a src-layout Python project
installed editable, which is Orkestra's own layout and the modern default, the
`.pth` holds a hardcoded absolute path to the main checkout:

```
$ cat .venv/lib/python3.12/site-packages/_editable_impl_orkestra_runtime.pth
/Users/andyyaro/Downloads/Orkestra/src
```

So, verbatim, in this repository:

```
$ git worktree add --detach /tmp/bg2 HEAD
$ echo 'raise RuntimeError("SABOTAGED")' > /tmp/bg2/src/orkestra/policy/engine.py
$ cd /tmp/bg2 && PATH=<main venv>/bin:$PATH pytest -q tests/unit/ -p no:cacheprovider
   ... all pass, exit code 0
$ python -c "import orkestra.policy.engine as e; print(e.__file__)"
/Users/andyyaro/Downloads/Orkestra/src/orkestra/policy/engine.py
```

Two things make this severe rather than academic. `pytest -q` is the exact
command `docs/CONFIGURATION.md` (lines 83 and 102) and every shipped example
prescribe, and `cli/detect.py:40` auto-detects it for any project without a
`uv.lock`. And the failure is silent and always false-clean: an unbound gate
cannot fail, so everything built on it is a confident falsehood.

Confirmed mitigations: `uv run pytest` re-resolves per directory and **does**
catch the sabotage; a worktree-scoped `PYTHONPATH` prepend also catches it, and
`PYTHONPATH` is already in `_ENV_ALLOWLIST` at `verify/runner.py:33`.

Full research report (7 directions, adversarial critique, judge panel):
`INNOVATION_RESEARCH.md` in the session scratchpad. Implementation of its first
three increments was dispatched to a second workflow; see §8.

---

This replaces the conversation you no longer have. Trust the repo over this
document where they disagree, and verify anything load-bearing before relying
on it — that discipline is itself one of the working agreements below.

---

## 1. What this project is

**Orkestra** — an open-source, local-first orchestration runtime that makes two
or more coding-agent CLIs (Claude Code, Codex CLI, Antigravity/`agy`) collaborate
on one project. A **deterministic non-LLM kernel** enforces policy, git-worktree
isolation, verification, and independent cross-agent review; an LLM **director**
proposes plans. Governing principle: *intelligence proposes, determinism
disposes.*

- Repo: `github.com/andyyaro/orkestra` · PyPI: `orkestra-runtime`
- Python ≥3.12, uv, Apache-2.0, stdlib `sqlite3` (WAL, no ORM — ADR-0003)
- Zero network calls by Orkestra itself; no API keys — agents authenticate
  through their own CLIs under the user's existing subscriptions
- Everything redacted at write time (`src/orkestra/redact.py`)

**Current state (verified at handoff):**

| Fact | Value |
|---|---|
| `main` | `f44e8ce` (PR #15). NOTE: pre-2026-08-19 SHAs in this document are dead, see the header. |
| Version / PyPI latest | **0.5.3** / **0.5.3** — published 2026-07-26 (run 30187355296, user-approved gate), verified behaviorally in a fresh isolated install (demo lifecycle green + merge-sha wiring visible in the published wheel) |
| Tests | **486 passed, 1 skipped** on `main` at 2026-09-08; green in the 7-check matrix on PRs #12 through #15 |
| Tags | v0.1.0 … v0.5.3 (annotated tag on `f50e87d`; GitHub release cut) |
| Open PRs | none. #6 was closed unmerged on 2026-08-19. |

---

## 2. Architecture map (where things live)

```
src/orkestra/
  kernel/scheduler.py    Orchestrator: execute() loop, _run_task, _verify,
                         _review, _render_brief, _gate_commands, apply_decision
  kernel/prepare.py      prepare_run: analyze → probes → plan → challenge
  kernel/explain.py      plain-language blocked-task explanations
  director/service.py    DirectorService._ask (structured exchanges), usage_sink
  adapters/              claude_code, codex_cli, antigravity_cli, gemini_cli,
                         fake (practice), external (orkestra-jsonl/1), docker
  verify/runner.py       run_verification, gate_command_problem, VerificationOutcome
  workspace/git.py       GitRepo (argv-only, hooks disabled), add_all_and_commit
  workspace/worktrees.py WorkspaceManager: create/commit/validate/integrate
  store/                 migrations.py (linear SQL list), repo.py (Store), db.py
  cli/main.py            the whole CLI surface; start.py = guided wizard
  report/final.py        build_report / render_markdown / render_json
  schemas/               config.py (ProjectConfig), agent.py, task.py, effort.py
```

Key kernel invariants a reviewer must know:

- `mutating = task.spec.mutates_repo and kind in MUTATING_KINDS` decides whether
  work is committed and integrated. **`mutating=True` with `commit is None`
  falls through to `keep_branch=False`** — the worktree is discarded exactly
  like a non-mutating task's.
- Since v0.5.3, `merge_no_ff()` and `integrate()` return the **merge commit
  sha** (`str`), or `None` on conflict — no longer `bool`. Task-done events
  carry `merge_sha` in their data; `orkestra accept` appends a durable
  `run_accepted` event (payload: `target_branch`, `integration_branch`,
  `merge_sha`).
- Since v0.5.0 the user's `[verify]` commands are **authoritative and run on
  every task**; plan-proposed `acceptance` entries run only *in addition* and
  only if `gate_command_problem()` says they're runnable. **Command identity is
  therefore not task identity** — this fact caused the worst defect found in
  PR #6.
- Verification runs inside the task's isolated worktree, so a pass in one
  worktree is not evidence about another task.

---

## 3. Release history and why each shipped

| Version | What it was |
|---|---|
| 0.1.0–0.3.0 | Initial build, Antigravity pivot, PyPI trusted publishing, quota-aware scheduling, Docker sandbox design, Textual TUI, UX/progressive-disclosure work |
| 0.4.0 | `orkestra start` guided journey, presets, per-agent model/effort, model discovery |
| 0.4.1 | **Git safety**: `start`/`init` never touch pre-existing uncommitted work; `review`/`accept` journey with hard partial-run enforcement |
| 0.4.2 | Fleet #1 fixes (wizard prompt loop, honest verification wording, idempotent accept, error paths) |
| 0.4.3 | `--agents` restriction, `report --save`, practice-mode honesty |
| 0.4.4 | Nested-repo guard, pre-mutation validation, full doc-staleness audit |
| 0.4.5 | Fleet #2 fixes (zero-mutation `--agents`, guard on every command, honest headlines) |
| **0.5.0** | **Verification authority correction** (fleet #3, real agents): `[verify]` is the gate; plan acceptance validated/dropped; broken gate blocks pre-flight; failure stdout/stderr captured into events *and* repair context; resume re-plans prep-interrupted runs; usage accounting covers planning/challenges/probes + cached tokens |
| **0.5.1** | **Hotfix** — my v0.5.0 `git add -A -- . :(exclude)…` made git hard-fail whenever those paths were ignored, so **no task could commit in any repo with a normal `.gitignore`**. Now `git add -A` + post-hoc unstage. Also retry dead-end (worktree before branch deletion), silent discard warnings, prose-acceptance validator |
| **0.5.2** | Fleet #4 tier 2: agents told the truth about their sandbox (they cannot run commands headlessly — stop asking), `run_commands` opt-in, planning scaled to plan size, run liveness in `status`, honest counts, test detection reads what tests import |
| **0.5.3** | **PR #6 review commitments** (PR #10): retry briefs fence replayed gate output between `<<<BEGIN/END COMMAND OUTPUT>>>` markers as data-not-instructions; `merge_no_ff()`/`integrate()` return the merge sha; task-done events carry `merge_sha`; `orkestra accept` records the durable `run_accepted` event (Provalume's `ACCEPTED_USER` hook); demo failure path made self-diagnosing after the py3.12/macOS CI flake proved undebuggable from one sample |

---

## 4. The fleet-testing method (the most valuable working pattern)

Four fleets so far. Each launches simulated first-time users as subagents, each
in an isolated PyPI install, knowing only the public docs, then dedupes findings
and has skeptical verifiers **reproduce each bug before it counts**.

- **Fleets #1–#2** (Sonnet testers, fake practice agents): UX/CLI defects → 0.4.2, 0.4.3, 0.4.5
- **Fleets #3–#4** (Opus testers, **three real Sonnet identities** as the
  orchestrated agents via `claude-code` multi-profiles): reached the
  verification pipeline and found that the *product's central claim* was false
  → 0.5.0, then 0.5.1, 0.5.2

Reports: `docs/development/FLEET_TEST_REPORT_v0.4.1.md`, `_v0.4.4.md`,
`_v0.5.0_REAL_AGENTS.md`.

**The workflow scripts persist and are reusable** — don't rewrite 200 lines of
persona definitions from scratch:

```
~/.claude/projects/-Users-andyyaro-Downloads-Orkestra/*/workflows/scripts/
  orkestra-user-fleet-wf_f43a88f3-3cd.js        fleet #1 (10 personas, fake agents)
  orkestra-user-fleet-v2-wf_f60f9b7f-541.js     fleet #2 (regression + new-surface)
  orkestra-fleet3-real-agents-wf_632d8878-ab3.js fleet #3 (6 Opus, 3 real Sonnet ids)
  orkestra-fleet4-real-agents-wf_e311fa0f-3f7.js fleet #4 (verification under load)
  memory-system-research-wf_6c5379ce-75e.js      the build-vs-adopt research sweep
```

Adapt fleet #4's script for fleet #5 (change the target version, the CONTEXT
block describing what's new, and the persona list). Its structure — sanitized
PATH for quota safety, one real-agent persona, per-change HELD/REGRESSED
verdicts in the schema — is the version worth copying.

**Launch shape** (Workflow tool): personas → dedupe → verify, with a sanitized
`PATH` for practice-mode personas (zero provider quota) and full `PATH` for the
one real-agent persona. Two fleets lost an agent to transient API errors; relaunch
that persona standalone and fold its report in manually — don't restart the fleet.

**What fleets keep proving:** fake agents cannot find pipeline defects. Real
agents found the verification-authority bug, the staging regression, and the
permission-stall waste. Budget ≈ 0.7–1M workflow tokens per fleet plus real
provider spend (fleet #4 real runs: ~$8.52 across two orchestrations).

---

## 5. CLOSED THREAD: PR #6 (Provalume memory integration)

**PR #6 was closed unmerged on 2026-08-19.** Everything below is kept as the
record of the review and its findings, which are still the best worked example
of the "correct events, inert feature" defect shape, and because the
reproducers `exp1`-`exp7` remain on disk and still run. It is not a live
thread and nothing here is waiting on anyone.

Not my branch. Authored by the user (`andyyaro`), **draft, 8/8 green, unmerged**.
Wires Orkestra into **Provalume** (`github.com/andyyaro/provalume`) — the
verification-grounded memory system, built as its own repo exactly as the
research recommended (§7). Optional by construction: without `provalume`
installed, `open_memory()` returns `None` and every call site no-ops.

### My adversarial review (completed)

I reviewed it because I own the kernel it hooks into and didn't write it. I ran
the integration rather than read it, which is the only reason the findings exist.

**Reproducers are saved durably at
`~/.claude/projects/-Users-andyyaro-Downloads-Orkestra/artifacts/pr6-repros/`**
(`exp1`–`exp7`, 8 files — `exp7_abort_dangling_run.py` added 2026-07-26). The
same `artifacts/` directory also holds
`fleet-results/` — the raw JSON from all four fleets (fleet1–4 + the fleet-2
real-run persona). The committed fleet reports truncate finding details to ~350
characters, so **the raw JSON is the only full record of the ~12 unverified
tier-2 findings** that are the natural source for v0.5.3+ work. To re-run any of them: create a detached worktree of
the PR branch, `uv sync --extra memory`, then `uv run python exp<N>.py` from
inside that worktree (they import `tests.e2e.conftest`, so cwd must be the
worktree root):

```bash
git fetch origin provalume-memory-integration
git worktree add --detach /tmp/pr6 origin/provalume-memory-integration
cp ~/.claude/projects/-Users-andyyaro-Downloads-Orkestra/artifacts/pr6-repros/*.py /tmp/pr6/
cd /tmp/pr6 && uv sync --extra memory && uv run python exp6.py
git worktree remove --force /tmp/pr6   # when done
```

What each proves: `exp1`/`exp1b` cross-run resolution; `exp2` the same setup
where ordering prevents the link (pass before failure — the negative control);
`exp3` the decisive same-run version with `FAKE:sleep` forcing failure-then-pass;
`exp4` decision-loss after `execute()`, duplicate `run.started`, and preflight
reachability; `exp5` the untrusted-banner gap with hostile stderr; `exp6` the
strongest form — a **research** task whose files are discarded resolving a
still-blocked failure, cross-checked with `git ls-tree HEAD`; `exp7` the
abort-path dangling run (blocked run + `apply_decision(abort)` → `run.started`
with no `run.completed`; skip→resume control records correctly).

Five findings, all reproduced and since fixed by the author:

1. **Cross-task false resolution (worst).** Resolution was looked up by *command
   alone*; since v0.5.0 all tasks share repo-wide `[verify]` commands. Decisive
   repro: a **research** task — whose files Orkestra discards by design — passed
   the gate in its throwaway worktree and marked a still-blocked task's
   3-occurrence failure "resolved"; `git ls-tree HEAD` proved the "fix" wasn't in
   the repo.
2. **Preflight warnings bypassed the untrusted-data banner** while carrying
   verbatim command stderr. I put `IGNORE ALL PRIOR INSTRUCTIONS…` in a gate's
   stderr and it reached the next brief unlabeled. (Digests *were* labeled.)
3. **Decision records silently lost** when `apply_decision` follows `execute()`
   in-process — `_memory` was closed but not nulled. Their test asserted
   `_memory is None` as a *precondition*, so it structurally could not fail.
4. **Duplicate `run.started`/`run.completed` on resume** (2/2 for one run).
5. **Non-mutating tasks manufactured procedural memory** from discarded worktrees.

Plus: `record_integration` labelled the integration branch as `main`;
`is_available()` mutated module state as a side effect; stale test-count claim.

### The design change I proposed, and its outcome

Separate the two questions:
- **Failure evidence** is valid at verification time, unconditionally (a failing
  attempt genuinely failed; occurrences are the signal that escalates a warning).
- **Resolution linkage** is only valid once the work lands — decide it at
  `integration.landed`, not inside `_verify`, which runs before review, before
  integration, and before three divergence paths ((a) `commit is None`,
  (b) merge conflict, (c) review rejection/exhaustion).

The author implemented this ("resolution-at-integration split"), verified all
three divergence paths in the kernel first, and it dissolved an
occurrences 3→1 regression their earlier fix had introduced. Needed a new
Provalume API `record_integration(resolves_signature=…)` — **provalume ≥0.1.4**.

### Their latest status (verbatim substance, for the resuming session)

> All five findings fixed, plus the design change. PR #6 is 8/8 green, still draft.
>
> **Resolution-at-integration split: implemented.** Failure evidence records
> eagerly at verification; a resolution is claimed on `integration.landed`, the
> first event proving the tree changed. Verified occurrences stays at 3.
>
> Implementing it surfaced **three more defects in freshly written code**, all
> caught by re-running rather than reading:
> 1. A landing names no command, so `what_later_worked` rendered "(nothing
>    recorded yet)" though the link was correct. Now reads "work landed on
>    `ork/<run>/integration` as commit abc123456789".
> 2. The branch fix was half a fix — payload corrected but the event envelope
>    column still read `main`, because `record_integration` captured `branch` as
>    a named parameter and wrote it only to the payload. Both now agree, which
>    fully settles the target point.
> 3. Every landing re-anchored every record on its branch, so all three
>    integrated records wore the last commit to land. Promotion is branch-wide;
>    re-anchoring shouldn't be. Three tasks now land in three distinct commits,
>    each record anchored to its own (cross-checked with `git branch --contains`).
>
> **Sha question: recommendation taken.** Task commit stays as the evidence sha;
> the landing now names `ork/<run>/integration` rather than reading as `main`.
>
> **Accept-time rung: yes please, if still willing.** Provalume already models
> `target="user"` → `ACCEPTED_USER`, a stronger state than `INTEGRATED_RUN`, and
> it is currently unreachable from Orkestra — another documented-but-dead
> capability. If `merge_no_ff` returns the sha, they'll wire
> `record_accepted(run_id, branch, merge_sha)` on their side. Not blocking.
>
> **Caveat now in the PR body:** with `adapter = "fake"`, the commit a resolution
> names is a placeholder — practice agents write `notes.md` and never implement
> the spec, so the "retry code" came from the human-authored base commit. The
> link is correct and the commit genuinely landed, but it is **not** evidence
> that memory pointed at the change that fixed anything. Needs real agents and
> real quota; first entry in Provalume's `LIMITATIONS.md`.
>
> **Residual documented as LIMITATIONS.md §9a:** signatures are keyed on command
> and error rather than task, so under a repo-wide gate a sibling's landing can
> resolve a signature a still-blocked task shares. Only landed work can resolve
> anything (enforced and tested), but a blocked task's owner wouldn't assume
> that, so it's stated plainly.

### Round three (2026-07-26): their trajectory benchmark

They replayed captured OrkestraAdapter calls from real runs of `18457c2`
(4/4 trajectories; recording semantics verified — occurrences 1→2→3→4,
resolution only at landing, per-command preflight correct). My response
(PR #6 comment): **(a)** their abort-gap claim CONFIRMED via
`exp7_abort_dangling_run.py` (saved with exp1–6): `apply_decision(abort)`
is the only in-process run terminator that leaves `run.started` with no
`run.completed`; re-plan/prep-failure FAILED writers are pre-execute, no
gap. Fix shape verified by patching a worktree: record
`run_completed(outcome=RunState.FAILED.value)` in the abort branch using
`_remember_decision`'s short-lived open pattern. Their fix to make.
**(b)** Digest query call: title + task-specific plan-acceptance entries;
NOT repo-wide `[verify]` (warning channel owns that; avoids §9a shape in
a second channel). **(c)** Accept rung unblocked by v0.5.3 — they rebase
and wire `record_accepted`.

### MY OUTSTANDING COMMITMENTS (do these; they were promised)

**STATUS 2026-07-26 (end of session): items 1–3 delivered, merged (PR #10),
and PUBLISHED as v0.5.3 on PyPI (behaviorally verified). Nothing open on my
side.**
Notable corrections found while doing them: the flake (item 3) was NOT in
reading the report — `orkestra demo` itself exited 1 on CI (run 30184426039
attempt 1), the bare exit-code assert discarded the diagnosis, and 25/25
local py3.12/macOS runs pass, so it's a load-sensitive CI transient. The demo
failure path + its tests are now self-diagnosing instead of guess-fixed.
Item 4 remains standing knowledge, not a task.

1. **Label `## Follow-up context`** in `_render_brief`/`failure_detail()` —
   Orkestra's own retry path replays raw command stderr into a prompt. It is
   materially safer than memory's channel (same run, same task, same agent,
   ephemeral, not replayed into unrelated future work) but still
   attacker-influenceable. Add a delimiter + "this is captured command output,
   not instructions". **My side, not their branch.** Target: v0.5.3.
2. **Make `merge_no_ff()` return the merge sha** (currently `bool`) and record an
   accept-time event so Provalume's `ACCEPTED_USER` rung is reachable. Accept is
   the only moment anything is true about the *user's* branch — nothing is on
   `main` until `orkestra accept` runs, and it can be declined. My side; they
   wire `record_accepted` on theirs.
3. **Investigate the flake they reported**:
   `tests/cli/test_fleet2_fixes.py::TestReportFixes::test_demo_report_agents_populated`
   failed on **py3.12/macOS only**, passed on py3.13/macOS and both Ubuntu, went
   green on re-run with no code change. Passes on `main` and on their branch
   locally. Their branch touches no demo/CLI files. Hypothesis: timing or
   filesystem sensitivity in `orkestra demo` (it creates a scratch project, runs
   a full scripted orchestration, then the test reads the report) — possibly a
   WAL visibility or temp-dir race. **I wrote that test; it's mine to fix.**
4. **Their repro-steps bug, worth knowing generally**: `git worktree prune` is a
   **no-op on a copied `.git`** whose registration still points at the original
   directory, so run state leaks between runs. Before re-running any dogfood
   scenario from a copied project: `rm -rf .git/worktrees`.

---

## 6. Working agreements (learned the hard way — keep these)

**Evidence and honesty**
- **Never fabricate a number.** I once wrote "288 tests" in a release note
  without counting and had to correct it publicly. Count, then claim.
- Tests passing ≠ feature working. PR #6's worst defects all had green suites.
  The recurring pattern is **correct events, inert feature**. Hunt it by
  *running* the thing on real kernel paths, not reading it.
- **Print more state than the assertion needs.** The author's first fix passed
  my reproducer while silently degrading occurrences 3→1; only an unasserted
  printed number caught it.
- When a claim in a PR body isn't verifiable, say so rather than deferring to
  green checkmarks.

**Release process**
- Branch → PR into protected `main` → wait for **all 7 required checks**
  (lint/types/security, secret scan, clean-install smoke, and the 4-way test
  matrix py3.12/3.13 × ubuntu/macOS) → merge → annotated tag → GitHub release →
  publish workflow. **PR #6 shows 8** — it adds a memory-extra test job.
- **PyPI publishing is OIDC trusted publishing** (project `orkestra-runtime`,
  workflow `publish-to-pypi.yml`, environment `pypi`, reviewer `andyyaro`).
  **Never use or request an API token.**
- The `pypi` deployment gate **requires explicit per-version approval from the
  user**. Approve via
  `gh api -X POST repos/andyyaro/orkestra/actions/runs/<id>/pending_deployments
  -F "environment_ids[]=<envid>" -f state=approved` — only after they say so.
- **Never move a tag; never overwrite a published version.**
- After publishing, verify **behaviorally** in a fresh isolated env
  (`UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` + `uv tool install orkestra-runtime==<v>`),
  not just `--version`.

**Quality gates (all must pass before a PR)**
```
uv run pytest -p no:cacheprovider
uv run ruff format . && uv run ruff check .
uv run mypy src                       # strict
uv run bandit -q -c pyproject.toml -r src
uv run pip-audit
uv build && uvx twine check --strict dist/*
```

**Traps that have bitten before**
- **Rich markup eats bracketed text**: `[verify]`, `[tui]`, `[claude]` vanish
  from console output unless escaped (`\\[verify]`) or passed through
  `rich.markup.escape`. This has caused three separate bugs.
- `bandit` `# nosec` must sit on the **flagged line**, separate from ruff
  `# noqa`.
- `ruff --fix` removes "unused" `# noqa`, which has silently broken later
  string-replacement patches — always `grep` to confirm a patch landed.
- Migration tests hard-coding `version == 1` break when a migration is added —
  assert `len(MIGRATIONS)`.
- Editing `.orkestra/config.toml` with regex mangles it; write it whole.
- GitHub push protection + gitleaks flag realistic-looking fake keys in
  fixtures; keep scanner-safe shapes and the `.gitleaks.toml` allowlist.
- pyproject sets `addopts = "-q"`, so running `pytest -q` yourself is
  double-quiet and the pass/fail **summary line disappears** — run without
  `-q` when you need numbers to claim (bit three times on 2026-07-26).
- **Never gate destructive steps on a piped command's exit code**:
  `gh pr checks --watch | tail` + `gh pr merge | tail` + `&&` made a failed
  merge look successful (tail exits 0), and the follow-on branch deletion
  closed PR #11 unmerged. Watch checks unpiped, verify `state=MERGED` via
  `gh pr view --json state,mergedAt` before deleting anything. GitHub API
  connections also reset transiently tonight — retry loops, not chains.

**Dogfood rule**: a dirty tree (tracked/staged changes) blocks `orkestra
start`/`run` by design. Untracked files do **not** block.

---

## 6b. Known limitations of Orkestra itself (as shipped)

From `BUILD_STATUS.md`, still true at v0.5.3 — say these plainly rather than
discovering them again:

- **Antigravity (`agy`) headless mode can silently skip file writes** under its
  default permission policy (status SUCCESS, no files). The verification gate
  catches it; see `docs/TROUBLESHOOTING.md`.
- **Gemini CLI adapter needs API-key/Vertex/Enterprise auth** — consumer Google
  OAuth was dropped by that CLI in June 2026, which is why `agy` is the
  first-party Google adapter.
- **Docker sandbox covers external/fake agents only** (ADR-0009). First-party
  CLIs run unsandboxed under their own permission systems.
- **Windows is untested.** Process-group and worktree semantics differ.
- **Agents cannot run commands headlessly by default** — since v0.5.2 the brief
  says so explicitly instead of letting them burn turns asking; `run_commands =
  true` per agent opts in.

## 7. Memory-system research (background for PR #6)

`docs/research/MEMORY_SYSTEM_RESEARCH.md` (+ `.docx`) — deep research, 6
specialists + a completeness critic. Conclusion: **build thin, don't adopt an
engine.** Every major engine (Mem0, Letta, Zep/Graphiti, Cognee, MemOS) puts an
LLM in the memory write path and defaults to cloud APIs; the category has a
rug-pull record (Zep killed self-hosting, Letta's flagship repo is legacy, Kuzu
archived). The generic "local-first cross-CLI memory" niche is already taken by
claude-mem (88.5k★). **The open gap is verification-grounded memory** — facts
your agents *proved* (which command passed, which reviewer approved, which
commit landed), which nobody else can produce without a deterministic kernel.
Provalume is that idea built out.

---

## 8. Where to pick up

`main` is clean, green (486 passed, 1 skipped) and 6 commits ahead of the v0.5.3
tag, unreleased. Nothing is half-done. In order:

1. **The unbound gate (see the header).** This is the highest-value item and it
   is a live defect in the product's central claim, reproduced twice. A second
   workflow was dispatched to implement the first three increments of the
   research plan on three branches:
   `bound-gate-binding-canary`, `bound-gate-verification-records`,
   `bound-gate-work-loss-guard`. Check whether those branches exist on origin,
   review them by RUNNING the sabotage reproduction rather than reading the
   diff, and open PRs for whatever survives. The canary branch is the one that
   matters; the other two are worth little without it.
2. **The docs and examples ship the vulnerable command.** `docs/CONFIGURATION.md`
   lines 83 and 102, every `examples/*/config.toml`, and `cli/detect.py:40` all
   prescribe or auto-detect bare `pytest -q`. Even without the canary, saying so
   plainly in the docs is a real improvement.
3. **A release.** Six unreleased commits sit on `main`, including a real bug fix
   (#15). v0.5.4 is justified. Remember the publishing rules in §6: trusted
   publishing only, never a token, and the `pypi` gate needs the user's explicit
   per-version approval.
4. **Fleet #5**, still worth doing, now with genuinely new surface: the injection
   fence, `run_commands`, the liveness signal, and if it lands, the canary. The
   user prefers to review the persona list before launch.
5. **Real-project use.** Still never done, still the highest-value unknown. Note
   that the unbound-gate finding makes this more urgent, not less: a real run
   whose gate is not bound would prove nothing while appearing to prove
   everything.

Reusable workflow scripts from this session live beside the older fleet scripts
in `~/.claude/projects/-Users-andyyaro-Downloads-Orkestra/*/workflows/scripts/`:
`orkestra-innovation-research-*.js` (39 agents: ground, 7 framings, 3 adversarial
lenses each, 3 judges, synthesis, completeness critic) and
`orkestra-bound-gate-implementation-*.js` (build in isolated worktrees, then
verify each branch by running it).

**Tone/process the user prefers:** work autonomously, don't stop to ask for
permission on reversible work, set up task tracking for multi-step efforts, and
report outcomes plainly — including what failed. They pre-approve deployment
gates explicitly and expect me to stop for them. They value being told when I
broke something (v0.5.1 was my regression, found within hours and fixed) more
than they value a clean narrative.

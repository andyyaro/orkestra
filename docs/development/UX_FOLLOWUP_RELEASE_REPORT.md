# v0.4.1 Follow-up Release Report

Bounded corrective release after v0.4.0. Scope: `orkestra start` git
safety, a coherent `review → accept` journey, terminology and evidence
reconciliation. The deterministic kernel, safety guarantees, config
format, and advanced commands are unchanged.

## Initial problems

1. `orkestra start` (and `init`) created setup commits with
   `git add -A` semantics — pre-existing uncommitted user files could
   silently enter an Orkestra commit.
2. Accepting a run had no summary or confirmation.
3. Docs taught `review → accept`; the commands were `diff → merge`.
4. The success message led with `ork/<run>/integration`.
5. `BUILD_STATUS.md` was a stale snapshot presenting itself as current.
6. `merge` printed a warning but proceeded on incomplete runs.

## Chosen behavior

**start git safety.** Repository state is captured before any file is
written. Existing repositories with tracked *or staged* changes stop
immediately (exit 1, deterministic in non-interactive mode) with a
plain-language explanation and exact `git commit` / `git stash`
commands; nothing is written, staged, or committed — verified in
dogfood: no `.orkestra/`, no `SPEC.md`, index untouched. Untracked
files never block setup but can never enter Orkestra's commit either:
setup commits are pathspec-scoped to an explicit allowlist (only
`SPEC.md` / `.gitignore`, and only when Orkestra created or modified
them in that invocation), then verified against the actual commit
contents (`git show --name-only`) with a hard failure if anything else
appears. A repo-less directory containing user files gets the setup
commit (Orkestra files only) plus explicit baseline guidance
(`git add . && git commit -m "project baseline"`), and auto-run is
suppressed until a baseline exists. Empty directories keep the smooth
one-command experience. There is no "continue anyway" path.

**review → accept.** `orkestra review [--full]` summarizes state, task
counts, verification and independent-review outcomes, the starting
point in plain language, commits, and file statistics, and flags
partial results. `orkestra accept [--cleanup] [--yes]
[--allow-partial]` shows a preflight summary and asks
`Proceed…? [y/N]` (default **No**). It hard-refuses: incomplete runs
(unless `--allow-partial`, which explains what's missing, warns, and
still confirms unless `--yes`), tracked/staged working-tree changes,
untracked files the result would overwrite, and `ork/*` checkouts.
Conflicts abort cleanly with both sides intact and exact next steps.
`--cleanup` runs only after successful acceptance. `diff` and `merge`
are same-implementation aliases — `merge` now enforces the identical
rules (the warn-and-continue partial merge is gone; scripts that merged
partial runs must now pass `--allow-partial`, which is the point).

**Terminology.** `start → run/watch → review → accept` everywhere; the
completion message reports outcomes (tasks, verification, review,
tokens — dollar cost only when adapters report it) and next commands;
internal branch names appear only in advanced docs and reports.

## Code changed

- `src/orkestra/workspace/git.py`: `staged_changes()`,
  `commit_paths()` (pathspec-scoped), `commit_files_in()`
- `src/orkestra/cli/start.py`: pre-mutation state capture, dirty stop,
  allowlist commit + post-commit verification, baseline guidance
- `src/orkestra/cli/main.py`: `_RunSummary`/`_gather_run_summary`,
  `review`/`accept` + `diff`/`merge` aliases, `_print_completion`,
  `init` allowlist commit
- `src/orkestra/cli/demo.py`, docs (README, QUICKSTART, CLI, FAQ,
  TROUBLESHOOTING), `BUILD_STATUS.md`, `FINAL_BUILD_REPORT.md` label

## Tests added (22 new; suite 363 → 385)

- `tests/cli/test_start_git_safety.py` — 9 scenarios on real git repos
  (empty dir; clean repo; modified-tracked stop; staged stop;
  untracked untouched; no-commits-with-files baseline; allowlist
  handling; nothing unrelated staged; deterministic non-interactive
  behavior; v0.4-project compatibility)
- `tests/cli/test_review_accept.py` — 13 scenarios (review summary and
  --full; partial warning; confirm default No; prompt-yes; --yes;
  complete-run enforcement incl. merge alias; --allow-partial with and
  without --yes; internal-branch refusal; untracked-collision refusal;
  cleanup-only-after-success)
- Updated: alias tests, journey tests, demo/final-message wording tests

## Compatibility

- v0.2/v0.3/v0.4 configs: unchanged loading (existing migration tests
  still pass); no config fields added or removed.
- `diff`/`merge` still exist. Behavior change (intended, breaking for
  unsafe automation only): `merge` without `--yes` now prompts, and
  incomplete runs require `--allow-partial`.
- Old projects verified usable (test 11 + dogfood B).

## Quality gates (run 2026-07-25, branch ux-followup-v0.4.1)

- `uv run pytest -p no:cacheprovider`: **385 passed** (253s)
- ruff format/check: clean · mypy --strict: clean (66 files) ·
  bandit: 0 issues · pip-audit: no known vulnerabilities
- `uv build` + `twine check --strict`: both artifacts PASSED
- Fresh venv installs: wheel ✓ and sdist ✓ (`orkestra --version`)

## Dogfood (real subprocess terminals, isolated PATH, wheel build)

- **A empty dir**: `orkestra start proj --non-interactive --run` →
  practice mode → "Run complete — your verified result is ready" →
  `review` (status/verification/review lines) → `accept --yes
  --cleanup` → "accepted … tidied up 4 internal branch(es)". No git
  commands needed at any point.
- **B clean repo**: setup commit contained exactly `.gitignore`,
  `SPEC.md`; user commit history and files untouched.
- **C dirty repo** (modified tracked + staged + untracked): exit 1
  before any mutation; no `.orkestra/`, no `SPEC.md`; index and files
  byte-identical; message showed commit/stash commands.
- **D incomplete run**: `accept --yes` → exit 1 with resume guidance;
  `accept --allow-partial` → PARTIAL warning, `[y/N]` default declined
  → "nothing changed".

## Remaining limitations (honest)

- `orkestra start` on a dirty repo offers no in-tool remediation (by
  design this release); a guided "commit for me / stash for me" flow
  with explicit confirmation could come later.
- Scenario-C stop happens before `.gitignore` is written, so a rerun
  after the user commits handles everything — but the stop message
  doesn't yet mention rerunning `orkestra start` explicitly enough.
- `merge`'s new prompting may surprise old scripts until they add
  `--yes` (called out in the changelog).

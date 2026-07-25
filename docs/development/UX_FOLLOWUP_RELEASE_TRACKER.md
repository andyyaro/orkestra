# UX Follow-up Release Tracker (v0.4.1)

Bounded corrective release: git safety in `orkestra start`, a coherent
`review → accept` journey, terminology reconciliation, and evidence
hygiene. No kernel changes, no compatibility breaks.

## Starting state (verified 2026-07-25)

- Branch `main` @ `91df987` (== `origin/main`), working tree clean
- Tags: v0.1.1 … v0.4.0 (annotated); latest GitHub release v0.4.0
- Package/runtime version 0.4.0; PyPI `orkestra-runtime` 0.4.0
- CI: green on `main` and tag `v0.4.0`; publish workflow green
- Test baseline: **363 collected**, all passing
- Gates: `uv run pytest` · `ruff format --check` · `ruff check` ·
  `mypy` (strict) · `bandit -c pyproject.toml -r src` ·
  `pip-audit --skip-editable` · gitleaks (CI) · `uv build` +
  `twine check --strict`
- Work branch: `ux-followup-v0.4.1`

## Scoped issues

1. `orkestra start` uses `add_all_and_commit` → can absorb pre-existing
   uncommitted user work into its setup commit.
2. Accepting a run lacks a summary/confirmation step.
3. Docs said `review → accept`; commands were `diff → merge`.
4. Success message leads with internal `ork/<run>/integration` branch.
5. `BUILD_STATUS.md` / evidence stale (claims v0.2.0-era state).
6. `merge` warns but proceeds on partial runs.

## Implementation tasks

- [x] P1 start git-safety redesign (state capture; allowlist pathspec
      commit of SPEC.md/.gitignore only; dirty-repo stop with plain
      options; deterministic non-interactive failure; same allowlist
      commit applied to `init`)
- [x] P1 regression tests (11 scenarios, real git repos)
- [x] P2 `orkestra review` (+ `--full`; `diff` shares implementation)
- [x] P2 `orkestra accept` (preflight, confirm default No, `--yes`,
      complete-run enforcement, `--allow-partial`, untracked-collision
      check, ork/* refusal, safe conflict abort, cleanup only after
      success; `merge` = advanced alias, same rules)
- [x] P3 terminology sweep (final message, start output, README,
      QUICKSTART, CLI, FAQ, TROUBLESHOOTING, demo, tests)
- [x] P4 BUILD_STATUS current-state rewrite; FINAL_BUILD_REPORT labeled
      historical; release report written
- [ ] P5 full gates + fresh wheel/sdist installs
- [ ] P6 dogfood scenarios A–D recorded below
- [ ] P7 version 0.4.1, PR through protected main, tag, GitHub release,
      publish → pypi approval gate

## Tests required

- start: clean empty dir · clean repo · modified tracked file · staged
  file · untracked files · no-commits-with-files · SPEC/.gitignore
  handling · nothing unrelated staged · nothing unrelated in commit ·
  deterministic non-interactive dirty behavior · v0.4 projects usable
- journey: review · review --full · accept default-No · accept --yes ·
  complete-run enforcement · --allow-partial (+confirm) · dirty-tree
  rejection · ork/* rejection · successful accept · cleanup-only-after-
  success · diff/merge compatibility · final message wording ·
  config migration v0.2/v0.3/v0.4

## Verification evidence

- 2026-07-25: full suite after P1–P3 on branch `ux-followup-v0.4.1`:
  **385 passed** (`uv run pytest -p no:cacheprovider`, 253s); ruff/mypy
  clean at each commit (a9a464a, then review/accept and terminology
  commits)
- P1 suite: tests/cli/test_start_git_safety.py — 9 scenarios on real
  git repos, all passing
- P2 suite: tests/cli/test_review_accept.py — 13 scenarios, all passing

## Outcome

(pending)

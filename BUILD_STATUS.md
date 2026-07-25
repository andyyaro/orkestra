# Orkestra Status

**This is a current-state document.** Historical build evidence from the
original autonomous build lives in `FINAL_BUILD_REPORT.md` (labeled
historical) and `docs/development/evidence/`.

## Current state (2026-07-25)

- **Version:** 0.5.1 · latest published: **0.5.1** on
  [PyPI](https://pypi.org/project/orkestra-runtime/) and
  [GitHub releases](https://github.com/andyyaro/orkestra/releases)
- **Repository:** https://github.com/andyyaro/orkestra · default branch
  `main` · protected (7 required CI checks, no force pushes)
- **Quality gates (verified this date):** 464 tests passing · ruff
  format/lint clean · mypy `--strict` clean · bandit 0 findings ·
  pip-audit no known vulnerabilities · gitleaks clean in CI ·
  `twine check --strict` passing
- **User journey:** `orkestra start → run [--watch] → review → accept`
  (`init`/`diff`/`merge` remain as advanced/back-compat commands)

## Release history

| Version | Date | Theme |
|---|---|---|
| 0.4.1 | 2026-07-25 | Git-safety + review/accept UX correction |
| 0.4.2 | 2026-07-25 | Fleet-test fixes (wizard, honesty, idempotent accept, error paths) |
| 0.4.3 | 2026-07-25 | Agent selection (--agents), report --save, practice-mode honesty |
| 0.4.4 | 2026-07-25 | Nested-repo guard, pre-mutation validation, doc accuracy sweep |
| 0.4.5 | 2026-07-25 | Fleet #2 fixes (zero-mutation --agents, guard everywhere, honest headlines) |
| 0.5.0 | 2026-07-25 | Verification authority correction + usage accounting (fleet #3, real agents) |
| 0.5.1 | 2026-07-25 | Hotfix: staging regression blocking all tasks (fleet #4) |
| 0.4.0 | 2026-07-25 | Progressive-disclosure configuration (`orkestra start`, presets, neutral effort, model discovery) |
| 0.3.0 | 2026-07-25 | Usability (demo, diff/merge, plain-language gates, progress line) |
| 0.2.0 | 2026-07-25 | Quota-aware scheduling, Docker sandbox (external agents), TUI, session reuse |
| 0.1.2 | 2026-07-24 | PyPI Trusted Publishing |
| 0.1.1 | 2026-07-24 | Redaction hardening (from Orkestra's own dogfood review) |
| 0.1.0 | 2026-07-24 | Initial release: kernel, adapters, worktrees, director, gates |

## Verified claims (with where the evidence lives)

- Live cross-vendor orchestration with real Claude Code, Codex CLI, and
  Antigravity CLI, including gate-caught silent failure, fallback
  repair, and cross-vendor review approval —
  `docs/development/evidence/LIVE_SMOKE_REPORT.md` (historical,
  2026-07-24)
- Self-review dogfood whose findings shipped as v0.1.1 —
  `docs/development/SELF_REVIEW.md`
- v0.4.1 git-safety and journey verification —
  `docs/development/UX_FOLLOWUP_RELEASE_REPORT.md` and
  `docs/development/UX_FOLLOWUP_RELEASE_TRACKER.md`

## Known limitations (current)

- Antigravity headless mode can silently skip writes under its default
  permission policy (gates catch it; see TROUBLESHOOTING).
- Gemini CLI adapter requires API-key/Vertex/Enterprise auth.
- Docker sandbox covers external/fake agents only (ADR-0009).
- Windows untested. See `ROADMAP.md`.

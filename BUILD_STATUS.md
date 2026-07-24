# Orkestra Build Status

**Status:** IN_PROGRESS
**Phase:** 9 — Live validation and dogfooding (fake-agent E2E complete)
**Last updated:** 2026-07-24

## Phase checklist

- [x] Phase 0 — Bootstrap and environment inventory
- [x] Phase 1 — Research and architecture decision (docs/research/*, ADRs)
- [x] Phase 2 — Repository and quality foundation
- [x] Phase 3 — Core kernel and persistence
- [x] Phase 4 — Adapter layer (claude-code, codex-cli, antigravity-cli,
      gemini-cli, fake, external + contract kit)
- [x] Phase 5 — Git workspace and integration engine
- [x] Phase 6 — Director and capability system
- [x] Phase 7 — CLI and operator experience
- [x] Phase 8 — Policy, human gates, redaction (docker sandbox deferred
      honestly to v0.2 — refused with explanation, see ROADMAP)
- [ ] Phase 9 — E2E validation and dogfooding
  - [x] 15-scenario fake-agent E2E suite (2/3/5-agent runs, fallback,
        review rejection/repair, gate veto, decisions, interruption/
        resume, cancellation, merge-conflict recovery)
  - [x] Live smoke iterations 1–3 with real claude/codex/agy: director
        analysis, live probes, plan challenges verified; three kernel
        defects found and fixed (dirty-repo fail-fast, orphaned
        PLANNING runs, prose acceptance commands crashing the pipeline)
  - [ ] Full live run to COMPLETE (in progress)
  - [ ] Controlled self-review dogfood
- [ ] Phase 10 — Documentation ✔ (README + docs set written), packaging,
      GitHub publication, release

## Quality gates (current)

- 249 tests passing (unit, integration, E2E, CLI)
- Coverage 82% (floor 80)
- ruff clean, mypy --strict clean, bandit 0 findings, pip-audit clean

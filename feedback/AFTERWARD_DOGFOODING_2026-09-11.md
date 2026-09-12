# Dogfooding notes — embedding Orkestra 0.5.5 programmatically (Afterward build)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 (from PyPI) · **Context:** building "Afterward" (an AWS
Strands agent team) and evaluating Orkestra to (a) orchestrate part of the build and (b) share a plan/state
vocabulary. This is a **library / programmatic-embedding** perspective, complementary to the CLI-focused
`FLEET_TEST_REPORT_*` reports.

These are observations from real use, not a change list — what the experience was like, with the evidence behind each
note. What to do about any of it is entirely the maintainer's call.

Verification basis: installed `orkestra-runtime==0.5.5`, inspected the actual package with `inspect`/`pkgutil`, and
cross-checked every observation against the shipped `README.md`, `docs/INSTALL.md`, `docs/QUICKSTART.md`,
`docs/CLI.md`, `docs/CONCEPTS.md`. Nothing here is from memory.

## What felt good
- `orkestra demo` / `--offline` zero-token showcase is genuinely excellent onboarding — it's front-and-center in
  `README.md` and `docs/QUICKSTART.md`, and it made the lifecycle legible in a minute.
- The typed plan/state model (`DirectorPlan`, `PlannedTask`, `TaskSpec`, `Assignment`, `RunState`/`TaskState`) and the
  structured trace vocabulary (`AgentEvent`/`EventKind`, `AgentResult`/`ResultStatus`) are clean and well-shaped — it was
  a pleasure to read and to map onto another framework.
- The dogfooding-report culture itself (`FLEET_TEST_REPORT_v0.4.1`, `v0.4.5`) is a strong signal; it's why this note exists.

## What I observed (programmatic embedding)

### 1. The docs are CLI-first; the library API is undocumented territory
`README.md`, `INSTALL.md`, `QUICKSTART.md`, `CLI.md`, and `CONCEPTS.md` all document the **`orkestra` CLI**. Meanwhile
the package ships a substantial Python API — `orkestra.director.DirectorService`, `orkestra.schemas.*`,
`orkestra.policy.PolicyEngine`, `orkestra.adapters.registry.FakeAdapter`, `orkestra.store.Store`, `orkestra.app.build_app`.
To embed Orkestra I had to discover all of it by reading source with `inspect.signature`/`getsource`. The practical
effect: it wasn't clear whether programmatic use is even a supported, stable path or an internal one, so I couldn't tell
how much to rely on it.

### 2. Distribution name ≠ import name, with no import line anywhere to anchor on
Install is `pip install orkestra-runtime` (verified `INSTALL.md:32`); the import is `import orkestra`. Because every
documented example is CLI-based, there's no `import` line in the docs, so my first instinct — `import orkestra_runtime` —
failed with `ModuleNotFoundError` and I had to go find the real module name.

### 3. `DirectorService.validate_plan()` is a genuinely useful capability I only found by reading source
It's a **pure, no-LLM** validator: it builds a `TaskDag` over `depends_on` (cycle + unknown-dependency detection),
enforces the ≤25-task cap, and runs `PolicyEngine.check_assignment` + unknown-agent rejection — all with zero network
or model calls. That's exactly the kind of thing I wanted for offline plan-linting and unit tests, and I'd never have
known it existed without `getsource`. To use it I also had to assemble an `adapter` + `policy` + `work_dir` even though
I only wanted validation, which took some source-reading to get right.

### 4. The offline path exists for the CLI but I couldn't find its library equivalent
`--offline` is well documented for the CLI (`CONCEPTS.md:76`, `QUICKSTART.md:117`). The library equivalent I ended up
using — `DirectorService(..., offline=True)` with `FakeAdapter` — isn't mentioned anywhere I could find, so it took
trial-and-error to land on it. It turned out to be the key to exercising orchestration logic at $0 in CI.

### 5. `Orchestrator` isn't where a reader first looks
`orkestra.kernel` is empty at the top level (`dir(orkestra.kernel) == []`); the orchestrator actually lives at
`orkestra.kernel.scheduler.Orchestrator` (also referenced in `docs/research/MEMORY_SYSTEM_RESEARCH.md:90`). I went
looking in `orkestra.kernel` first and came up empty before finding it one level down.

## Net impression
The command/CLI surface reads as thorough and polished. For my specific use case — embedding Orkestra as a library —
the friction was entirely about discoverability: a real, capable Python API is there, but I learned it by reading source
rather than docs, so I couldn't gauge what was supported vs. internal. More notes to follow from actually running it.

# Dogfooding feedback — embedding Orkestra 0.5.5 programmatically (Afterward build)

**Date:** 2026-09-11 · **Version:** orkestra-runtime 0.5.5 (from PyPI) · **Context:** building "Afterward" (an AWS
Strands agent team) and evaluating Orkestra to (a) orchestrate part of the build itself and (b) share a plan/state
vocabulary. This is a **library / programmatic-embedding** perspective, complementary to the CLI-focused
`FLEET_TEST_REPORT_*` reports already in `docs/development/`.

Verification basis: installed `orkestra-runtime==0.5.5`, inspected the actual package with `inspect`/`pkgutil`, and
cross-checked every claim below against the shipped `README.md`, `docs/INSTALL.md`, `docs/QUICKSTART.md`,
`docs/CLI.md`, `docs/CONCEPTS.md`. No claim here is from memory.

## Praise first
- `orkestra demo` / `--offline` zero-token showcase is genuinely excellent onboarding DX — verified it is front-and-center
  in `README.md` and `docs/QUICKSTART.md`.
- The typed plan/state model (`DirectorPlan`, `PlannedTask`, `TaskSpec`, `Assignment`, `RunState`/`TaskState`) and the
  structured trace vocabulary (`AgentEvent`/`EventKind`, `AgentResult`/`ResultStatus`) are clean and well-shaped — a
  pleasure to map onto another framework.
- The dogfooding-report culture itself (`FLEET_TEST_REPORT_v0.4.1`, `v0.4.5`) is a strong signal. This report follows it.

## Issues found (programmatic embedding)

### 1. The programmatic/library API is effectively undocumented (docs are CLI-first)
`README.md`, `INSTALL.md`, `QUICKSTART.md`, `CLI.md`, `CONCEPTS.md` all document the **`orkestra` CLI**. But the package
ships a substantial Python API — `orkestra.director.DirectorService`, `orkestra.schemas.*`, `orkestra.policy.PolicyEngine`,
`orkestra.adapters.registry.FakeAdapter`, `orkestra.store.Store`, `orkestra.app.build_app` — with **no library-usage
guide**. To embed Orkestra I had to read source with `inspect.signature`/`getsource`.
**Ask:** add a `docs/LIBRARY.md` (or "Programmatic API" section) with the minimal embed path, OR state explicitly that
the CLI is the only supported surface and the Python API is internal/unstable.

### 2. Distribution name ≠ import name, and no docs line shows the import
Install is `pip install orkestra-runtime` (verified `INSTALL.md:32`), but the import is `import orkestra`. Because all
documented usage is CLI, there is no `import` line anywhere in the docs — so a library user's natural first guess,
`import orkestra_runtime`, fails with `ModuleNotFoundError`. **Ask:** if programmatic use is supported, document the
import name once, prominently.

### 3. `DirectorService.validate_plan()` is a hidden gem — surface it
`validate_plan(plan, agents)` is a **pure, no-LLM** validator: it builds a `TaskDag` over `depends_on` (cycle +
unknown-dep detection), enforces the ≤25-task cap, and runs `PolicyEngine.check_assignment` + unknown-agent rejection —
all with zero network/model calls. This is ideal for offline plan-linting and unit tests, but is discoverable only by
reading source. **Ask:** document it, ideally with a one-liner `DirectorService.for_validation(agents)` convenience
constructor so callers don't have to assemble `adapter + policy + work_dir` just to validate a plan.

### 4. The offline *programmatic* path is undocumented
`--offline` (CLI) is well documented (`CONCEPTS.md:76`, `QUICKSTART.md:117`). The **library** equivalent —
`DirectorService(..., offline=True)` with `FakeAdapter` — is not. It's the key to $0 CI tests of orchestration logic.
**Ask:** a short snippet in the library docs.

### 5. `Orchestrator` discoverability
`orkestra.kernel` is empty at the top level (`dir(orkestra.kernel) == []`); the orchestrator lives at
`orkestra.kernel.scheduler.Orchestrator` (confirmed; also referenced in `docs/research/MEMORY_SYSTEM_RESEARCH.md:90`).
A top-level re-export or a note in the library docs would save a source dive.

## Worth re-checking (not verified this session)
- The v0.4.1 report flagged that untracked files do **not** count toward the dirty-repo safety check (docs claimed they
  do). Worth confirming whether that's resolved in 0.5.5, since the "your branches are never touched" guarantee is a
  headline promise.

## Net
Command/CLI fidelity looks strong (per prior reports). The gap for *my* use case is purely documentation: a real,
useful programmatic API exists but is undocumented, so embedding requires source-reading. Closing #1–#5 would make
Orkestra straightforward to adopt as a library, not just a CLI. More feedback to follow as I actually run it during the
Afterward build.

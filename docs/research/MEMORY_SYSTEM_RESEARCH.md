# Build vs Adopt: A Memory System for Orkestra

**Deep research report — 2026-07-25**
**Question:** Orkestra needs a serious ("best ever") memory system, to be released as a separate open-source repo. Should we build one or adopt an existing open-source one?
**Method:** Six parallel research passes (major frameworks; emerging systems & local substrates; academic literature 2023–2026; cross-CLI/multi-agent memory landscape; licensing & OSS strategy; Orkestra codebase integration analysis), followed by an adversarial completeness review that verified load-bearing claims against primary sources (GitHub API, official vendor docs, papers). All star counts and benchmark numbers are point-in-time (July 2026) and, where vendor-reported, should be treated as marketing-adjacent.

---

## 1. Executive summary and recommendation

**Recommendation: build — but build thin, deterministic, and boring, and adopt the substrates.** Do **not** adopt any existing memory *engine* (Mem0, Letta, Zep/Graphiti, Cognee, MemOS) as the core. Do **not** build a generic "agent memory" project — that field is saturated and you would be two years late. Build a small, orchestration-specific memory layer **inside Orkestra first**, on parts you already trust (SQLite WAL + FTS5, later sqlite-vec + a local static embedder), differentiated on the one axis nobody serves: **verification-grounded, cross-agent memory** — facts your agents *proved* (tests passed, independent review approved, merge landed), not things an LLM said. Spin it out as a separate repo only after it has proven itself inside Orkestra, following the Graphiti/Beads extraction pattern. Confidence: ~75% (the strategy researcher's estimate, which I share; the residual 25% is dominated by two things you can resolve cheaply — see §8).

The four load-bearing findings behind this:

1. **Every major adoptable engine violates Orkestra's core constraints by design.** Mem0, Letta, Graphiti, Cognee, and MemOS all require an LLM call in the critical write path (extraction/consolidation) and default to cloud APIs. "Fully local via Ollama" exists for each but is a second-class, friction-documented path — and it would bolt a nondeterministic LLM dependency onto a kernel whose entire identity is "intelligence proposes, determinism disposes."
2. **The category has a rug-pull and abandonment record.** Zep killed its self-hosted Community Edition (April 2025). Letta's flagship 24k-star repo is now officially legacy. Kuzu — an MIT-licensed embedded graph DB, and Cognee's *default* graph backend — was archived outright in October 2025 after an Apple acqui-hire, stranding downstream users. Graphiti carries a single-vendor CLA. Depending on a VC-backed memory engine is a real strategic risk, not a hypothetical.
3. **The generic gap is already closed; the specific gap is genuinely open.** claude-mem (88.5k stars, Apache-2.0, multi-CLI, SQLite, rides the user's existing Claude subscription — verified via GitHub API, actively pushed as of 2026-07-23) owns "local-first, no-API-key, cross-CLI session memory." Beads (~18.7k stars) owns "git-native agent state." A long tail covers the rest. But **no released project stores what a deterministic kernel verified**, carries provenance like {agent, worktree, verification result, review verdict, commit SHA}, or is designed as orchestrator-owned memory injected across heterogeneous vendor CLIs. That is exactly, and only, Orkestra's standing.
4. **The literature has converged on "simple + files + schemas" beating "clever retrieval."** Letta's own benchmark showed a plain filesystem agent beating Mem0's graph variant; LongMemEval-V2's current leader is a file-based memory controller; Microsoft's LazyGraphRAG conceded GraphRAG's indexing costs; the durable value across ten canonical papers is in **schemas, write-triggers, and lifecycle policy** — all things a deterministic kernel does well without an LLM.

---

## 2. What "memory" should mean for Orkestra

The field's standard taxonomy (CoALA: working / episodic / semantic / procedural) is best used as a schema-design tool, because each type wants a different write, retention, and retrieval policy:

| Type | Contents for Orkestra | Write policy | Retrieval |
|---|---|---|---|
| **Episodic** | What happened: attempts, failures, fix cycles, review rejections | Append-only (already largely captured in `events`/`attempts`/`ledger`) | Recency-weighted, decays |
| **Semantic** | Facts about the repo/project: "we use pnpm now", "CI needs Node 20", environment gotchas | Upsert + **invalidation, never deletion** (bi-temporal: `valid_at`/`invalid_at`/`recorded_at`) | Hybrid lexical(+vector) |
| **Procedural** | Verified runbooks/skills: "how to run the flaky integration suite" | **Verify-before-promote** — only after passing Orkestra's verification once | By name/keyword |
| **Working** | The per-task context digest injected into a brief | Assembled at task time, budgeted | n/a (it *is* the output) |

LongMemEval-V2 (the only benchmark testing agent trajectories at 25M–115M tokens, i.e., the closest to Orkestra's reality) names the competencies that matter for coding agents: **workflow knowledge, environment gotchas, dynamic state tracking, premise awareness**. That is the checklist the schema should serve — not conversational QA recall.

---

## 3. The adoption candidates, honestly profiled

### 3.1 Major engines — all disqualified as the core

| System | License | Local/no-API-key | Fatal problem for Orkestra |
|---|---|---|---|
| **Mem0** (~60k★) | Apache-2.0 | Possible via Ollama, documented friction | 1–2 LLM calls on *every* memory write (extract, then ADD/UPDATE/DELETE/NOOP decision); needs a vector store; no non-LLM path exists |
| **Letta** (~23k★) | Apache-2.0 | Yes, quality degrades with small local models | It's an agent *runtime*, not a memory layer; wants Postgres in production (SQLite = dev-only, no migrations); **flagship repo now officially legacy** — development moved to Letta Code, a competing coding-agent product |
| **Zep / Graphiti** (high-teens–29k★, sources disagree) | Apache-2.0 **with CLA** | Partial — needs Neo4j (GPLv3) or FalkorDB (SSPL) plus a local LLM | Zep killed self-hosting (April 2025); Graphiti needs an external graph DB and LLM extraction; CLA keeps single-vendor relicensing open |
| **Cognee** (~29k★) | Apache-2.0 | Embedded defaults (SQLite+LanceDB+Kuzu) are genuinely closest to Orkestra — but quickstart requires an OpenAI key, and docs recommend 32B+ local models for reliable extraction | **Its default embedded graph DB, Kuzu, was archived Oct 2025** (verified: `archived=true`); reported indexing-reliability issues under load |
| **MemOS** (~10k★) | Apache-2.0 | "Local plugin" tier claims SQLite-only; self-hosted tier needs Neo4j+Qdrant | Research-flavored, heavyweight; vendor-run benchmarks; the exportable part is its governance *ideas*, not its code |
| **LangMem** (~1.6k★) | MIT | Extraction still needs an LLM | Pre-1.0, thin, practically coupled to LangChain/LangGraph — wrong shape for a non-LangChain runtime; best as a design reference |

The cross-cutting disqualifier: **all of them put an LLM in the write path**. You can point each at Ollama, but then Orkestra's memory quality depends on whichever local model the user happens to run, its extraction is nondeterministic and unreproducible across runs, and the "no API keys, zero network calls, deterministic kernel" story — Orkestra's entire differentiation — is compromised at the layer users would trust least well.

### 3.2 The nearest neighbors (closer to home than the engines)

These matter more than the big engines, both as prior art and as competitive signal:

- **claude-mem** (88.5k★, Apache-2.0, verified active) — hooks + SQLite + compression via the Claude Agent SDK, riding the user's existing subscription (the same no-API-key trick Orkestra uses). Now supports Claude Code, Codex, Gemini, Copilot, OpenCode. **This is the incumbent for cross-CLI session memory.** It is per-tool/session memory with no concept of verification, cross-agent review, or orchestration — but its roadmap could drift toward provenance features, which is the main competitive risk to the plan below.
- **Beads** (Steve Yegge, ~18.7k★) — issues-as-agent-memory: JSONL committed to git, SQLite as a cache, hash IDs for multi-agent merge safety, paired with his Gas Town orchestrator. **Proof that "git-native memory substrate + separate orchestrator" is a winning play**, and the closest strategic template for Orkestra+memory.
- **agentmemory** (rohitg00, ~25.7k★) — MCP memory server for coding CLIs. Caveat found by the verification pass: the repo is **five months old** (created 2026-02-25) with marketing-slogan positioning; treat its traction and "100% top-5 hit rate" benchmark claims skeptically until independently reproduced.
- **AIngram** — single-SQLite-file memory: sqlite-vec + FTS5 + optional knowledge graph fused via reciprocal rank fusion, local ONNX embeddings, Ed25519-signed entries. Small project, but **architecturally the closest published match to what Orkestra would build** — a reference implementation worth reading end to end.
- **ProjectMem** (MIT, has an arXiv paper) — event-sourced, append-only log of issues/attempts/fixes deterministically projected into summaries, with a **pre-action gate that warns agents before repeating a known-failed fix**. Verified across Claude Desktop, Cursor, Codex, and — notably — Antigravity. The pre-action gate is an idea Orkestra should steal outright.
- **SigmaLink** and **madebyaris/agent-orchestration** — the two nearest things to "orchestrator + memory": the former bundles memory inside an Electron multi-CLI orchestrator; the latter is an MCP server with project-level SQLite and namespaced memory (context/decisions/findings/blockers). Neither is a standalone, adoptable memory library with verification semantics. Worth a code read; not adoption targets.

**Direct competitor check:** no released project was found positioned as "orchestrator-owned, verification-grounded memory injected into multiple vendor CLIs, local-first, zero API keys." The generic space is crowded; this specific spot is empty.

---

## 4. What the research literature says to steal

Ten techniques with strong evidence, each with its cheapest LLM-free or LLM-optional implementation (full citations in §10):

1. **Two-tier file memory** (index + topic files, agent-written, human-auditable) — the Claude Code auto-memory pattern; the highest evidence-per-dollar design for coding agents. Zero infrastructure.
2. **Reflexion-style lessons keyed to verifier outcomes** — persist a structured "gotcha" record on every verification failure. Orkestra's kernel already produces the failure signal deterministically; this is the single best-validated technique for coding agents and it is nearly free.
3. **Bi-temporal facts with invalidation, never deletion** (from Zep/Graphiti — the *schema idea*, no LLM needed): `valid_at`/`invalid_at`/`recorded_at` + a `supersedes` foreign key. Coding facts churn; history must survive.
4. **Procedural runbooks with verify-before-promote** (Voyager → Memp → Agent Skills): a procedure enters the library only after it passed verification once.
5. **Recency × usage × relevance scoring with usage-weighted decay** (Generative Agents + MemoryBank): BM25 × exp-decay(age) × log(access_count). Demote, don't delete. Entirely LLM-free.
6. **Sleep-time consolidation as a scheduled job** (Letta): distill raw episodes into compact notes during idle time, using whichever agent CLI the user already has. LLM-*optional*: if the pass never runs, the system still works, just less compact.
7. **Lazy summarization** (LazyGraphRAG's lesson): never pay LLM indexing cost up front; store raw + cheap metadata at write time, refine only what gets read.
8. **Repo map as derived structural memory** (Aider): tree-sitter + reference-graph ranking; fully deterministic, rebuildable cache, gives every agent shared codebase awareness.
9. **Cheap graph linking at write time, PPR-lite at read time** (A-MEM + HippoRAG, minus their LLM costs): store k-NN/entity-overlap edges on insert; 1–2-hop spreading activation at read. Personalized PageRank over a SQLite edge table is ~50 lines of Python.
10. **Memory governance as first-class metadata** (MemOS's framing): every memory carries source episode ID, author agent, scope, and passes redaction at write. **No popular OSS memory system does this well today — it is the differentiator.**

On benchmarks: **LoCoMo is effectively discredited** (tiny contexts, gameable, and the Mem0-vs-Zep war ended with both vendors' headline numbers corrected downward; a third-party audit even found corrupted answer keys). LongMemEval v1 is saturating (93–96% claims). **LongMemEval-V2 is the one to care about** — agent trajectories at real scale, best system ~74.9%, and that system is a *file-based* memory controller. If the memory repo ever publishes numbers, publish LongMemEval-V2-style task-embedded evals plus your own replayable harness, and never market on LoCoMo.

---

## 5. Orkestra integration reality (from the codebase read)

The integration analysis (verified against actual source, file paths correct as of v0.4.2) found:

- **One prompt choke point.** `Orchestrator._render_brief()` in `src/orkestra/kernel/scheduler.py` builds the single instructions string every adapter receives (argv for the three CLIs, JSON-over-stdin for external agents). A memory digest spliced there reaches every agent with zero per-adapter code.
- **Worktree file injection is possible but has a trap.** Nothing writes CLAUDE.md/AGENTS.md into worktrees today, and `WorkspaceManager.commit_workspace()` runs `git add -A` over the whole worktree — any injected memory file would be swept into the agent's commit and pollute the reviewer's diff unless removed/ignored first. Any file-based injection must handle this explicitly.
- **Rich signal already exists.** `events` (append-only, redacted), `attempts` (per-agent results with a closed error taxonomy), `ledger` (per-agent task outcomes — the capability feedback loop), `observations` (probe/task capability evidence), `decisions` (human gates), `usage_log`. Review verdicts currently live only inside `attempts.result` JSON — a dedicated review table (or memory-side capture) is needed to learn from rejections.
- **Constraints to inherit:** Python ≥3.12, mypy strict, Apache-2.0, stdlib `sqlite3` WAL with idempotent writes (no ORM — ADR-0003), single-writer async discipline, redaction-at-write via `orkestra.redact`, and the four-dependency footprint (pydantic/typer/rich/tomlkit). A memory package that imports 100MB of onnxruntime by default would betray the project's character; heavy embedders must be optional extras.
- **Scoping:** per-project memory has an obvious home (`.orkestra/memory.db` or sibling files); **global cross-project memory is net-new territory** — nothing defines a `~/.orkestra/` today, and Orkestra deliberately rebuilds capability data per project. Ship per-project first; make global scope an explicit later decision.
- **Injection portability across the three CLIs is messier than folklore suggests** (verified on official docs): Codex reads AGENTS.md natively (32KB cap, silent truncation); Claude Code does **not** read AGENTS.md (Anthropic: "not planned"; requires a CLAUDE.md shim/import); Antigravity's AGENTS.md support is secondary-sourced only. The robust pattern is the hybrid every serious cross-CLI tool converged on: **a shared local store materialized into vendor-specific files per worktree, plus prompt-splice via the brief, plus (later) an MCP server surface.** Orkestra's kernel already owns both file-writing and invocation-shaping, so this is home turf.

---

## 6. Build vs adopt: the decision

### Adopt an engine? No.
Every engine fails at least two of: no-API-key by default, deterministic write path, SQLite-compatible footprint, dependency stability (Zep CE dead, Letta legacy, Kuzu archived, Graphiti CLA'd, FalkorDB SSPL). Adopting one means building Orkestra's differentiators (verification grounding, cross-agent provenance, redaction, git-native semantics) *on top of* someone else's pivot-prone foundation — most of the build work, plus the dependency risk, minus the identity.

### Adopt a nearest-neighbor (claude-mem / agentmemory)? Also no — but evaluate before committing.
The critic's sharpest point: this research is desk research; nobody installed anything. claude-mem in particular is the one genuinely unexamined adoption option. But even on its own description it is session-compression memory, per-tool, with no verification concept, no orchestrator hooks, and no schema you control. Wrapping it would mean depending on an 88k-star project whose roadmap you don't steer, for a component you want as your identity. **Do the 1–2 day hands-on trial of claude-mem, agentmemory, and madebyaris/agent-orchestration anyway** — as competitive intelligence and to steal UX patterns, and to falsify (cheaply) the assumption that none of them fits.

### Build generic? No.
"Memory repo #41" launches two years late into claude-mem's shadow. The strategy report is blunt about this and correct.

### Build specific? Yes.
The unserved position — verified via a hard search for incumbents — is:

> **Facts your agents proved, not things they said.** Verified, git-native memory for multi-agent coding: every entry carries provenance (which agent, which worktree, which verification command passed, which reviewer approved, which commit landed), written deterministically by an orchestration kernel, readable by any CLI.

Nobody else can credibly claim this because nobody else *has* a deterministic verification kernel generating the ground truth. That is a moat made of architecture, not effort.

---

## 7. Proposed architecture (v0 sketch)

**Working name suggestion:** something in the "proof/provenance" semantic field rather than the "memory" field (the memory namespace is exhausted).

**Stage 0 — deterministic core (no new dependencies at all):**
- Own SQLite file (`.orkestra/memory.db`), WAL, linear migrations, idempotent writes — same discipline as the kernel store.
- Tables: `memories` (id, type: episodic|semantic|procedural, text, scope, valid_at, invalid_at, recorded_at, supersedes_id, source_run, source_task, author_agent, verification_state, review_state, commit_sha, access_count, last_accessed), `edges` (k-NN/entity-overlap links), FTS5 index over text.
- **Writers are kernel events, not LLM extraction:** verification failure → gotcha record; review rejection → lesson record; human decision → decision record; run acceptance → promoted facts; repeated failure signature → pre-action warning (the ProjectMem gate).
- Retrieval: FTS5/BM25 × recency decay × log(usage), assembled into a budgeted digest, spliced into `_render_brief()` and the director's planning input. All redacted at write via the existing pipeline.
- Git-native export: JSONL under `.orkestra-memory/` (or in-repo, Beads-style) with hash IDs so teammates/machines merge without conflicts — decide single-machine vs team scope **before** v0 (the critic is right that this fork is cheaper to pick early; recommendation: design the IDs/merge semantics now, ship single-machine first).

**Stage 1 — optional semantic recall (extras, off by default):**
- `sqlite-vec` (MIT/Apache dual; pin the version — pre-1.0, bus factor 1) + `model2vec` static embeddings (MIT, ~30MB, CPU, numpy-only) behind an `Embedder` protocol; `fastembed` as the heavier alternative. Runtime capability check with FTS5-only fallback (python.org macOS builds sometimes lack `enable_load_extension` — verified present on this machine, not guaranteed for users).
- Hybrid BM25+vector via reciprocal rank fusion — the pattern the whole local-first field converged on.

**Stage 2 — LLM-optional distillation and surfaces:**
- Sleep-time consolidation as an Orkestra-scheduled job using the user's own agent CLIs (skippable; system degrades gracefully to "less compact," never to "broken").
- MCP server surface so non-Orkestra tools can read/write it — that's what makes the separate repo adoptable beyond Orkestra.
- Per-worktree materialization: canonical digest → AGENTS.md + CLAUDE.md shim + GEMINI.md, cleaned before `commit_workspace()`.

**Spin-out trigger:** extract to its own repo when (a) it has survived ≥1 month of real Orkestra dogfooding, (b) it has a one-sentence identity and a 60-second `uvx` quickstart, and (c) the MCP surface works from at least one non-Orkestra client. License MIT or Apache-2.0, **no CLA** (DCO at most).

**Effort estimate:** 4–8 focused solo weeks to a useful v0 with AI assistance (the strategy report's estimate; consistent with claude-mem/Beads shipping velocity). The real cost is the tail: eval harness, retrieval-quality ownership, cross-platform extension packaging.

---

## 8. Risks and honest counterarguments

1. **Memory poisoning is unmodeled — and it's your differentiator's Achilles heel.** (Critic's best catch.) Cross-agent shared memory creates a new attack path: agent A's possibly-prompt-injected output becomes persistent trusted context replayed into agent B's future prompts across sessions. Redaction handles credentials, not adversarial instructions. Mitigations that fit the design: only kernel-verified events auto-promote to trusted tiers; agent-authored prose stays in a quarantined tier labeled as such in digests; human-promotion gate (MemPalace-style inbox) for anything crossing scopes. **Write the threat model before writing code** — "trusted because verified" is only defensible if the trust boundary is real.
2. **claude-mem could absorb the niche.** 88.5k stars and 259 releases in seven months is terrifying execution speed. Your defense is the kernel: they cannot generate verification provenance without becoming an orchestrator. Ship the provenance schema early and visibly.
3. **The "files beat databases" evidence is partly vendor-circular.** Letta's filesystem-beats-Mem0 number is Letta's own blog on a discredited benchmark. The convergent direction (simple beats clever) is supported independently (LongMemEval-V2 leader, LazyGraphRAG), but hold the specific numbers loosely.
4. **ToS question on background distillation.** Sleep-time consolidation drives the user's Claude/Codex subscription from a scheduled job. claude-mem's flourishing suggests tolerance, but nobody verified the consumer-terms position. Keep distillation opt-in and user-triggered by default until checked.
5. **No requirements mining from real data yet.** Nobody has queried Orkestra's own `events`/`ledger` from real runs to rank which memory failures actually recur (repeated failed fixes? re-discovered gotchas?). Do this in week one — it turns the schema from speculation into evidence.
6. **Two facts in this report rest on secondary sources:** Antigravity's native AGENTS.md support, and the exact effect of the Claude adapter's `--setting-sources user` flag on CLAUDE.md auto-loading inside worktrees. Both are trivially testable on this machine and both gate the file-injection design. Test before building on them.
7. **Solo-maintainer surface growth.** A second repo means a second CI, release train, and issue tracker. The staged plan (inside Orkestra first) defers this cost until the component has earned it.

---

## 9. Recommended sequence

1. **Week 0 (before any code):** threat model for memory poisoning; mine real run data for recurring failure patterns; hands-on trial of claude-mem, agentmemory, madebyaris/agent-orchestration; locally verify the two untested injection facts (Antigravity AGENTS.md, `--setting-sources` behavior in worktrees); decide team-vs-single-machine merge semantics.
2. **Weeks 1–3:** Stage 0 deterministic core inside Orkestra (own DB, kernel-event writers, FTS5 retrieval, brief/director injection, redaction, tests at Orkestra's usual gate standard).
3. **Weeks 4–6:** dogfood on real runs; add the pre-action gate; build the replayable eval harness from your own captured trajectories.
4. **Then:** Stage 1 (optional vectors), MCP surface, worktree materialization — and only then the spin-out, with the one-liner: *"facts your agents proved, not things they said."*

---

## 10. Sources

**Primary vendor/docs sources:** Anthropic Claude Code memory docs (code.claude.com/docs/en/memory); OpenAI Codex Memories docs (learn.chatgpt.com/docs/customization/memories); Gemini CLI GEMINI.md docs (geminicli.com/docs/cli/gemini-md); agents.md; GitHub API verifications of claude-mem (88,520★, Apache-2.0, pushed 2026-07-23), agentmemory (created 2026-02-25), Kuzu (`archived=true`, last push 2025-10-10), Letta README (legacy notice), Cognee README (embedded defaults + LLM_API_KEY quickstart).

**Frameworks:** github.com/mem0ai/mem0 (+ docs.mem0.ai local-Ollama cookbook; issues #3274/#3439); github.com/letta-ai/letta (+ letta.com blog: memory blocks, v0.5, sleep-time compute, filesystem benchmark); github.com/getzep/graphiti (+ Zep-CLA.md; blog.getzep.com CE-deprecation and LoCoMo-dispute posts; getzep/zep-papers issue #5); github.com/topoteretes/cognee; github.com/MemTensor/MemOS; github.com/langchain-ai/langmem.

**Neighbors/substrates:** github.com/thedotmack/claude-mem; github.com/steveyegge/beads; github.com/rohitg00/agentmemory; github.com/bozbuilds/AIngram; github.com/riponcm/projectmem (arXiv 2606.12329); github.com/s1gmamale1/SigmaLink; github.com/madebyaris/agent-orchestration; github.com/jayzeng/agentmemory; mempalace; github.com/asg017/sqlite-vec; github.com/lancedb/lancedb; github.com/chroma-core/chroma; github.com/qdrant/fastembed; github.com/MinishLab/model2vec; The Register on Kuzu's archiving (2025-10-14).

**Papers:** MemGPT (arXiv 2310.08560); Generative Agents (2304.03442); MemoryBank (2305.10250); HippoRAG 2 (2502.14802, ICML 2025); A-MEM (2502.12110, NeurIPS 2025); RAPTOR (2401.18059); LazyGraphRAG (Microsoft Research blog); Zep temporal KG (2501.13956); Reflexion (2303.11366); MemOS (2507.03724); Voyager (2305.16291); Memp (2508.06433); CoALA (2309.02427); LongMemEval (2410.10813) and LongMemEval-V2 (xiaowu0162.github.io/longmemeval-v2); MemBench (2506.21605); "Memory in the Age of AI Agents" survey (2512.13564).

**Orkestra internals:** src/orkestra/kernel/scheduler.py, workspace/worktrees.py, store/migrations.py, store/db.py, store/repo.py, redact.py, director/prompts.py, adapters/*, docs/adapters/PROTOCOL.md, pyproject.toml (verified in-tree at v0.4.2).

*Caveats: this is desk research plus codebase analysis — no candidate system was installed and benchmarked hands-on (flagged as step 1 of the recommended sequence). Star counts are July-2026 snapshots and varied up to 2× between research passes for fast-moving repos; all vendor benchmark numbers in this space have a documented history of correction and should never be quoted as settled.*

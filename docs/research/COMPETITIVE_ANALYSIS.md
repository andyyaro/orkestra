# Competitive Analysis

Retrieved 2026-07-24. Star counts and versions are approximate and
fast-moving; see sources at the end.

## Landscape

### API-layer multi-agent frameworks (different market)

| Project | Profile | License |
|---|---|---|
| **LangGraph** (~24.8k★) | Graph orchestration of LLM API calls; checkpointing; production standard. No CLI-agent workers, no worktrees, routing developer-coded. | MIT |
| **Microsoft Agent Framework** (AutoGen + Semantic Kernel successor, 1.0 GA ~2026-04) | Deterministic "workflow orchestration" mode exists - closest big-vendor analogue to a deterministic kernel - but API-layer and Azure-oriented. | MIT lineage (unified repo license unconfirmed) |
| **CrewAI** (~45k★) | Role-based crews; LLM manager for hierarchical mode; static roles. | MIT |
| **OpenAI Agents SDK** (~26k★, Swarm successor) | Minimal handoff-based orchestration of API agents; guardrails. | MIT |

None orchestrate subscription-authenticated CLI agents; none do worktree
isolation or measured capability delegation.

### Coding-agent orchestrators (Orkestra's market)

| Project | Subscription CLIs | Local-first | Deterministic control | Worktrees | Dynamic capability delegation |
|---|---|---|---|---|---|
| Claude Code **Agent Teams** (official, experimental, 2026-02) | Claude only | Yes | No (LLM lead) | Convention only | No |
| **Ruflo** (ex-claude-flow, ~65k★, TS/Rust, MIT) | Claude-centric | Yes | Mixed (swarm topologies + learned routing) | Not core | Learned routing, opaque; not an evidence matrix |
| **claude-squad** (~8.1k★, Go) / **cmux** (~24.8k★) / Conductor / Crystal / Emdash tier | Yes | Yes | **Human** control | Yes | No |
| **Vibe Kanban** (~27.5k★, Rust/TS, Apache-2.0) - *sunsetting per its README* | Yes | Yes | Human kanban | Yes | No |
| **Bernstein** (~730★, solo-maintained, Python, Apache-2.0) | Yes | Yes (air-gap) | **Yes** - one LLM plan call, then plain Python | Yes | **No - static YAML routing, explicitly "no runtime capability negotiation"** |
| **zeroshot** (~1.6k★, MIT) | Yes | Yes | Fixed pipeline (planner → implementer → blind validators) | Yes/Docker | No (fixed roles) |
| OpenHands (~70k+★), SWE-agent, gpt-pilot (abandoned; had a 2025-26 supply-chain incident), Devin (SaaS) | Mostly API | varies | No | No | No |

Small/embryonic adjacents: AgentsMesh (BSL), toryo ("trust-based
delegation", embryonic), Dex, kodo, Orkas, loki-mode. High churn;
several projects in this tier are already archived.

## Where Orkestra is meaningfully different

1. **Separated powers.** Session managers have a human kernel and no
   director; Agent Teams/Ruflo have an LLM director and no enforcing
   kernel; Bernstein has a deterministic kernel and deliberately *no*
   runtime director. Nobody ships *dynamic LLM director proposes, non-LLM
   kernel disposes* - schema-validated decisions, policy enforcement,
   isolation, gates, and review independent of what any model claims.
2. **Evidence-based capability matrix.** No mature project measures
   demonstrated per-agent strengths from kernel-recorded outcomes and
   re-weights delegation. Ruflo's learned routing is opaque and
   Claude-centric; Bernstein's routing is static YAML.
3. **Kernel-enforced cross-vendor independent review.** zeroshot's blind
   validators and Bernstein's cross-model review come closest; neither
   pairs it with dynamic delegation. Orkestra makes `implementer ≠
   reviewer` a structural guarantee.
4. **Subscription-auth economics as a design center.** Flat-rate
   Claude/Codex/Gemini plans make local multi-agent development
   affordable; API-layer frameworks structurally can't serve this, and
   CLI orchestrators treat quota awareness as incidental.

## Risks

- **Bernstein** is architecturally adjacent (deterministic kernel,
  worktrees, verification gates); Orkestra must be visibly differentiated
  by the dynamic director + capability matrix.
- Official vendor tools could expand - though vendor incentives cut
  against orchestrating a competitor's CLI, which favors a neutral
  open-source runtime.
- Category fatigue: claims must stay verifiable (evidence artifacts, not
  feature lists).

## Sources (retrieved 2026-07-24)

- https://github.com/andyrewlee/awesome-agent-orchestrators ; https://github.com/bradAGI/awesome-cli-coding-agents
- https://github.com/sipyourdrink-ltd/bernstein ; https://bernstein.run/
- https://github.com/ruvnet/claude-flow ; https://github.com/BloopAI/vibe-kanban ; https://github.com/covibes/zeroshot
- https://github.com/openai/swarm (deprecation) ; https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/ ; https://learn.microsoft.com/en-us/agent-framework/overview/
- https://www.langchain.com/resources/ai-agent-frameworks ; https://blog.jetbrains.com/pycharm/2026/06/top-agentic-frameworks-for-building-applications-2026/
- https://blog.imseankim.com/claude-code-team-mode-multi-agent-orchestration-march-2026/ (Agent Teams)
- https://github.com/Pythagora-io/gpt-pilot (abandonment/supply-chain incident)
- Additional listings: securityboulevard.com, vibecodinghub.org, starlog.is (see research transcript)

Uncertainties: star counts ±15%; Microsoft Agent Framework unified-repo
license and claude-squad license unconfirmed; Ruflo performance claims
self-reported and contested; embryonic projects assessed from directory
listings only.

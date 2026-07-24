# Research Method

Date: 2026-07-24

## Goal

Select the architecture, stack, integration approach, license, and name for
Orkestra with evidence rather than assumption, before implementation.

## Method

1. **Local primary evidence first.** The installed agent CLIs are the ground
   truth for integration surfaces. We captured `--help` output and ran one
   minimal live probe per authenticated CLI to record real output shapes
   (see `samples/`). Probes were single-turn "Reply OK" prompts to minimize
   quota usage.
2. **Official documentation.** Parallel research tracks used official product
   docs, repositories, and release notes for: competitive landscape, provider
   terms and authentication constraints, agent integration surfaces, and
   licensing/naming. Every claim used for a decision carries a URL and
   retrieval date.
3. **Weighted decision matrix.** Stack and framework choices are scored in
   `TECH_STACK_DECISION.md` against explicit weighted criteria (defined
   there), covering the sixteen criteria required by the build specification.
4. **Adversarial review.** Research conclusions were checked against the
   product's non-negotiable principles (deterministic kernel, no fixed-three
   assumptions, safe defaults) before acceptance.

## Research tracks and outputs

| Track | Output |
|---|---|
| Environment and CLI surfaces | `ENVIRONMENT_INVENTORY.md`, `samples/` |
| Competitive landscape | `COMPETITIVE_ANALYSIS.md` |
| Agent integration | `AGENT_INTEGRATION_RESEARCH.md` |
| Stack selection | `TECH_STACK_DECISION.md` |
| Licensing and naming | `LICENSING_AND_NAMING_REVIEW.md` |
| Provider terms and auth | `TERMS_AND_AUTHENTICATION_REVIEW.md` |
| Security | `../security/THREAT_MODEL.md` |
| Architecture | `../architecture/ARCHITECTURE.md`, `../architecture/adr/` |

## Source-quality rules

- Primary sources (official docs, installed binaries, official repos) are
  required for critical claims (integration flags, terms, licenses).
- Secondary sources (blogs, discussions) may only supplement.
- No large copyrighted passages are copied; findings are summarized.
- Retrieval dates are recorded because agent CLI surfaces change quickly.

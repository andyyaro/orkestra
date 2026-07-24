# ADR-0007: License — Apache-2.0; distribution name `orkestra-runtime`

Date: 2026-07-24 · Status: accepted

## Context

See `docs/research/LICENSING_AND_NAMING_REVIEW.md`. Goals: broad
adoption, patent safety, clean coexistence with the vendor CLIs we
orchestrate, and a defensible position in a crowded "Orkestra"
namespace. The bare PyPI name `orkestra` is occupied by an abandoned
unrelated project; npm `orkestra` is occupied by an active unrelated
project.

## Decision

- License the repository **Apache-2.0** with `LICENSE` and `NOTICE`.
- Product name **Orkestra**; GitHub repo `andyyaro/orkestra`; PyPI
  distribution name **`orkestra-runtime`**; import package `orkestra`;
  CLI command `orkestra`.
- README carries trademark attribution and a no-affiliation disclaimer
  for Anthropic PBC, OpenAI, and Google LLC.

## Rationale

Apache-2.0 adds an express patent grant, explicit contribution terms,
and a trademark non-grant clause over MIT at no adoption cost, and
matches Codex CLI / Gemini CLI licensing. MPL-2.0's file-level copyleft
adds friction without ecosystem precedent.

## Consequences

- A future PEP 541 request could reclaim the bare PyPI name; not a
  dependency.
- Contributions are accepted under Apache-2.0 §5 (inbound=outbound), no
  CLA needed.

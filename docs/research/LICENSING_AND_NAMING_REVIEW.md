# Licensing and Naming Review

Research retrieved 2026-07-24 (WebSearch/WebFetch against registries and
official sources).

## Name availability

| Registry / space | `orkestra` status | Notes |
|---|---|---|
| PyPI | **Taken** — "Airflow + AWS" tool by knowsuchagency, v0.9.4, MIT, last release 2021-06-16; backing repo dormant since 2024 | Variants `orkestra-cli`, `orkestra-core`, `orkestra-runtime`, `orkestrator`, `pyorkestra` all available (404 on PyPI JSON API) |
| npm | Taken — unrelated Node worker-thread framework, v0.0.1, published 2026-06 | Scoped `@andyyaro/orkestra` always available |
| crates.io | Available | |
| GitHub | Many unrelated repos (Azure/orkestra K8s tool, dead 2023; imperativelabs/orkestra LLM router, small; burakdemir16/Orkestra-CLI, TS) | Repo names are per-owner; `andyyaro/orkestra` is fine |
| Companies | Orkestra Energy (AU clean-energy SaaS), French data-orchestration firm, Salesforce-plugin firm | None in coding-agent/dev-tool space; "Orkestra" is a weakly protectable common word |

### Decision

- **Product / repo name:** `Orkestra` at `github.com/andyyaro/orkestra`
  (per-owner uniqueness; no active dev-tools trademark conflict).
- **PyPI distribution name:** **`orkestra-runtime`** (available; matches
  "orchestration runtime" positioning). Top-level import stays
  `orkestra`. A PEP 541 transfer request for the bare PyPI name is a
  possible future step, not a dependency.
- Registry publication is out of scope for v0.1 anyway (no PyPI
  credentials in this environment); the name is reserved in metadata.

## License comparison

Adjacent projects (verified via GitHub API): LangGraph MIT; AutoGen MIT
(code) + CC-BY-4.0 (docs); CrewAI MIT; OpenAI Agents SDK MIT; **Codex CLI
Apache-2.0; Gemini CLI Apache-2.0; Google ADK Apache-2.0**; Claude Code
proprietary.

| Criterion | MIT | Apache-2.0 | MPL-2.0 |
|---|---|---|---|
| Adoption friction | none | none | some (file-level copyleft) |
| Patent grant + retaliation | no | **yes** | yes |
| Contribution terms (inbound=outbound) | implicit | **explicit (§5)** | explicit |
| Trademark non-grant clause | no | **yes (§6)** — useful in a crowded namespace | partial |
| Ecosystem fit | common | matches the vendor CLIs we orchestrate | unused in this space |
| Interaction with orchestrating proprietary CLIs | n/a — subprocess invocation creates no derivative work under any of these | same | same |

### Decision

**Apache-2.0** (ADR-0007): satisfies adoption + patent-safety goals,
matches Codex CLI and Gemini CLI licensing (keeps any future
code-level reference clean), and its trademark clause suits the crowded
"Orkestra" namespace. `LICENSE` + `NOTICE` files; SPDX headers optional.

## Vendor trademark / branding constraints

- **Anthropic:** Trademark Guidelines are conservative on logos/brand
  usage and approval, silent on referential compatibility naming;
  ecosystem practice (`claude-code-*` third-party projects, Anthropic's
  own `claude-code-action`) supports descriptive adapter IDs. No logos;
  no implied endorsement.
- **OpenAI:** brand guidance requires your product name first ("Orkestra
  … for OpenAI Codex", never "OpenAI Orkestra"); referential module
  naming is standard practice; Codex CLI itself is Apache-2.0.
- **Google:** explicitly permits "for / for use with / compatible with
  <mark>" phrasing including in app titles; marks must not join the
  product's own name/domain; attribute "Gemini is a trademark of Google
  LLC."

### Applied rules

1. Adapter IDs are lowercase descriptive identifiers: `claude-code`,
   `codex-cli`, `gemini-cli`.
2. Vendor marks stay out of the top-level package name.
3. README carries: "Works with Claude Code, OpenAI Codex CLI, and Google
   Gemini CLI" plus a trademark-attribution and no-affiliation footer
   (Anthropic PBC, OpenAI, Google LLC).
4. No vendor logos anywhere; no "official" claims.

## Sources (retrieved 2026-07-24)

- https://pypi.org/project/orkestra/ ; https://pypi.org/pypi/orkestra/json (+ variant 404 checks)
- https://registry.npmjs.org/orkestra ; https://crates.io/api/v1/crates?q=orkestra
- https://github.com/Azure/orkestra ; https://github.com/knowsuchagency/orkestra ; https://github.com/imperativelabs/orkestra ; https://github.com/burakdemir16/Orkestra-CLI
- License fields via GitHub API: langchain-ai/langgraph, microsoft/autogen (LICENSE-CODE), crewAIInc/crewAI, openai/openai-agents-python, openai/codex, google-gemini/gemini-cli, google/adk-python, anthropics/claude-code
- https://peps.python.org/pep-0541/
- https://www.anthropic.com/legal/trademark-guidelines ; https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms
- https://openai.com/brand (fetch blocked; summarized via search excerpts)
- https://partnermarketinghub.withgoogle.com/brands/google/trademarks-and-terms/trademark-guidelines-for-proper-usage/

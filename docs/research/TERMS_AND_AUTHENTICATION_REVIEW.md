# Provider Terms and Authentication Review

Retrieved 2026-07-24. This review governs what Orkestra does and
deliberately does not do. Summary: **Orkestra launches each official
CLI, unmodified, on the user's own machine under the user's own login,
and never touches credential stores.** That is the pattern each vendor
themselves ships for automation.

## Claude Code (Anthropic)

- Headless `claude -p` is a first-class documented feature; Anthropic
  ships subscription-auth automation itself (`claude setup-token`,
  official GitHub Action using `CLAUDE_CODE_OAUTH_TOKEN`).
- Legal & compliance page (post Feb-2026 tightening): OAuth is for
  subscribers' "ordinary use of Claude Code and other native Anthropic
  applications"; third-party developers must not offer Claude.ai login
  or route requests through Pro/Max credentials **on behalf of their
  users**; Agent SDK products should use API keys.
- Reading for Orkestra: a local tool the subscriber runs themselves,
  spawning the official binary under their own login, is consistent
  with ordinary use. Prohibited patterns (hosted multi-user services on
  consumer credentials, token extraction) are architecturally absent.
- Rate limits: 5-hour rolling session + weekly cap(s), pooled across
  Claude surfaces; only multipliers published. Orkestra treats limit
  signals (`api_retry` category `rate_limit`) as hard backpressure.

## Codex CLI (OpenAI)

- `codex exec` is built for scripts/CI ("Compose with scripts and CI").
  API key (`CODEX_API_KEY`) is the recommended automation credential;
  ChatGPT-account auth in CI is documented as advanced/trusted-private
  (one machine or serialized stream per auth copy).
- CLI is Apache-2.0; maintainers confirm forking/wrapping is
  license-permitted, while declining a blanket ToS blessing for
  third-party clients on ChatGPT OAuth. Shelling out to the unmodified
  binary under the user's own sign-in is the least-risk documented
  pattern, and the one Orkestra uses.
- ToU constraints honored: no credential sharing, no `auth.json`
  reading, no multiplexing one auth across users, no limit evasion.
- Limits: shared 5-hour window + weekly limits (credits overflow);
  per-token if API key.

## Antigravity CLI (Google) — first-party Google adapter

- Google migrated individual/Pro/Ultra consumer OAuth off the legacy
  Gemini CLI (2026-06-18) to the Antigravity suite; `agy` is the
  consumer-path CLI. Headless use (`agy -p`, print-mode OAuth, headless
  settings enforcement) is clearly contemplated by Google's docs and
  codelab.
- **ToS gray area (disclosed to users):** Antigravity's terms prohibit
  "using third party software, tools, or services to access the
  Service (e.g. using OpenClaw with Antigravity OAuth)". The clear
  target is harnesses consuming Antigravity OAuth/backends directly;
  whether launching the unmodified official binary under the user's own
  login is covered is unresolved, with no official ruling. Orkestra
  documents this prominently (README + `orkestra doctor`) and never
  touches OAuth material; see `ANTIGRAVITY_CLI_RESEARCH.md`.
- Quotas: plan-based (free weekly; Pro/Ultra 5-hour + weekly), shared
  across IDE + CLI, numbers unpublished → rate-limit errors are hard
  backpressure.
- agy is proprietary (binaries only); that does not affect Orkestra's
  Apache-2.0 licensing (subprocess boundary).

## Gemini CLI (Google) — non-default adapter

- Headless mode is official with documented exit codes; automation
  tutorial covers CI use. Free personal OAuth: 1,000 requests/day
  (AI Pro/Ultra: 1,500/2,000); free API key: 250/day Flash-only.
- Terms depend on auth method (Code Assist terms for OAuth — note the
  individuals tier may use prompts/responses for product improvement;
  Gemini API terms for keys; GCP terms for Vertex).
- No published prohibition on third-party tools invoking the binary;
  official CI action uses API keys/WIF rather than personal OAuth.
- On this machine Gemini is unauthenticated; interactive Google login is
  a user-only step. The adapter detects this deterministically (exit 41
  + JSON error, `samples/gemini-auth-error.json`) and reports it via
  `orkestra doctor`.

## Rules Orkestra enforces on itself

1. Launch official, unmodified CLIs only; official auth flows only.
2. Never read, copy, move, or transplant credential stores
   (`~/.claude`, `~/.codex/auth.json`, `~/.gemini`) — not even to check
   auth: readiness is probed via each CLI's own status/error surfaces.
3. Never present provider login UI as an Orkestra feature; `orkestra
   doctor` tells the user to run the vendor's own login command.
4. One local user, their own subscriptions; no multi-user brokering.
5. Rate-limit and auth-failure signals are terminal backpressure for
   the affected agent: bounded backoff, then fallback agent or human
   gate. Never retry-storm, never rotate accounts.
6. Usage metadata is recorded for reporting, not for limit evasion.
7. Documentation tells users that agent usage draws on their own plan
   limits and that parallelism multiplies consumption.

## Open uncertainties (tracked)

- "Ordinary, individual usage" (Anthropic) is not quantified; Orkestra's
  default concurrency is conservative (2) and quota signals are hard
  backpressure.
- OpenAI has not published a safe-harbor for third-party invocation of
  `codex` under ChatGPT auth; unmodified-binary subprocess is the
  minimal-risk reading.
- Reported mid-2026 Codex 5-hour-limit relaxation is unverified against
  official docs.

## Key sources (retrieved 2026-07-24)

- https://code.claude.com/docs/en/legal-and-compliance ; /headless ; /authentication
- https://support.claude.com/en/articles/11647753 ; /9797557 ; /11145838
- https://www.anthropic.com/legal/consumer-terms
- https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md
- https://developers.openai.com/codex/cli ; /codex/non-interactive-mode ; /codex/auth ; /codex/auth/ci-cd-auth ; /codex/pricing
- https://github.com/openai/codex/discussions/8338
- https://geminicli.com/docs/resources/quota-and-pricing/ ; /docs/resources/tos-privacy/ ; /docs/cli/headless/
- https://github.com/google-github-actions/run-gemini-cli/blob/main/docs/authentication.md

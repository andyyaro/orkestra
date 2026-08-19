# Provider Notes: Terms, Auth, and Limits

Summary of `research/TERMS_AND_AUTHENTICATION_REVIEW.md` and
`research/ANTIGRAVITY_CLI_RESEARCH.md` (retrieved 2026-07-24; provider
policies change - **review your providers' current terms yourself**).

Orkestra's universal posture: it launches each **official, unmodified
CLI** on **your machine** under **your own login**, never touches
credential stores, never proxies logins for other users, and treats
rate-limit signals as hard backpressure. Those are the patterns each
vendor themselves ships for automation - but responsibility for
compliant use of your accounts is yours.

## Claude Code (`claude`)

- Headless `claude -p` is an officially documented surface; Anthropic
  ships subscription-auth automation (setup-token, GitHub Action).
- Anthropic's legal page limits consumer OAuth to "ordinary use of
  Claude Code" by the subscriber and forbids third-party *services*
  from routing requests through consumer credentials. A local
  orchestrator you run yourself fits the former pattern; Orkestra's
  conservative default concurrency (2) reflects the undefined
  "ordinary, individual usage" phrase.
- Limits: 5-hour rolling window + weekly caps, pooled across Claude
  surfaces. Parallel agents consume it faster.

## OpenAI Codex CLI (`codex`)

- `codex exec` is built for scripts/pipelines per OpenAI's docs. API-key
  auth (an OpenAI API key in the Codex CLI's own configuration) is the
  recommended automation credential; Orkestra never reads or forwards it;
  ChatGPT-account auth is fine interactively/locally, and documented for
  CI only as "advanced, trusted private" use.
- OpenAI permits forking/wrapping the Apache-2.0 CLI but has not issued
  a blanket ToS ruling on third-party clients riding ChatGPT OAuth;
  launching the unmodified binary under your own sign-in is the
  minimal-risk documented pattern.
- Limits: shared 5-hour window + weekly limits (credits overflow).

## Google Antigravity CLI (`agy`) - default Google adapter

- Google migrated individual/Pro/Ultra consumer OAuth off the legacy
  Gemini CLI to Antigravity (2026-06-18). `agy -p` headless use is
  documented (codelab, print-mode OAuth).
- ⚠️ **Gray area, disclosed:** Antigravity's terms state that "using
  third party software, tools, or services to access the Service" (their
  example: OpenClaw with Antigravity OAuth) breaches the agreement. The
  clear target is tools consuming Antigravity OAuth/backends directly -
  Orkestra does not do that - but whether launching the unmodified
  binary under your own login is covered has no official answer yet.
  Orkestra surfaces this note in `orkestra doctor`; decide for yourself.
- agy is proprietary (binaries only), releases every few days; the
  adapter feature-detects and falls back to plain-text parsing.
- Limits: plan-based, shared across IDE + CLI (free: weekly; Pro/Ultra:
  5-hour + weekly), exact numbers unpublished.

## Google Gemini CLI (`gemini`) - non-default adapter

- Still Apache-2.0 and maintained, but consumer Google-account OAuth is
  no longer served. Valid auth: `GEMINI_API_KEY` (free tier: 250
  req/day Flash-only; paid per token), Vertex AI, or Code Assist
  Standard/Enterprise licenses.
- Orkestra's adapter reports auth-not-ready deterministically (exit 41)
  and directs consumer users to `antigravity-cli`.

## What Orkestra will never do (all providers)

- Read, copy, or transplant OAuth tokens or credential files.
- Offer provider login as an Orkestra feature or serve multiple users
  from one subscription.
- Evade rate limits (no retry storms, no account rotation).
- Silently switch you to paid API billing.

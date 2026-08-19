# Antigravity CLI (`agy`) Research

Retrieved 2026-07-24. Combines official-docs research with live local
verification on agy 1.1.6 (this machine). Where the two conflict, local
primary evidence is noted explicitly.

## Product context

- Google Antigravity is Google's agentic development platform (desktop
  IDE since Nov 2025; CLI since Antigravity 2.0, 2026-05-19). The CLI is
  a single Go binary (`agy`), multi-agent capable, default model in the
  Gemini 3.5 Flash family.
- On **2026-06-18** Google stopped serving Gemini CLI / Code Assist IDE
  requests for individual, Google AI Pro, and Ultra consumer OAuth; the
  Antigravity CLI is the designated replacement. This matches the
  migration error observed on this machine.
- Distribution: `curl -fsSL https://antigravity.google/cli/install.sh |
  bash`; repo `github.com/google-antigravity/antigravity-cli` hosts
  binaries and issues only - **no source, no LICENSE: agy is
  proprietary**, unlike Apache-2.0 gemini-cli.
- Release cadence ~2–4 days (1.1.0 → 1.1.6 within July 2026); adapters
  must tolerate drift and feature-detect.
- Config: `~/.gemini/antigravity-cli/` (settings.json, plugins/,
  skills/); workspace MCP config `.agents/mcp_config.json`.

## Automation surface - docs vs. local verification

| Capability | Docs/community said | Verified locally on 1.1.6 |
|---|---|---|
| `-p/--print` headless | confirmed, plain text only | ✅ works |
| `--output-format json` | "probably doesn't exist" (feature requests #7/#76 open) | ✅ **works**: envelope `conversation_id`, `status`, `response`, `duration_seconds`, `num_turns`, `usage` (`samples/antigravity-print-json.json`) |
| `--output-format stream-json` | uncertain | ✅ **works**: `init` / `step_update` / `result` JSONL (`samples/antigravity-stream-jsonl.jsonl`) |
| Conversation-ID capture in print mode | "impossible" (issue #7) | ✅ possible via the JSON envelope's `conversation_id` |
| Non-TTY stdout drop/hang (#76, #318, reported on 1.0.x) | open issues | ✅ did **not** reproduce: piped/redirected runs returned full output, exit 0 |
| `--print-timeout` (default 5m) | third-party refs | ✅ listed in `--help` |
| `--conversation <id>` resume, `--mode accept-edits\|plan`, `--dangerously-skip-permissions`, `--sandbox`, `--add-dir`, `--model`, `--effort` | confirmed | ✅ listed in `--help` |

Adapter consequences: use `--output-format stream-json` with a
feature-detection fallback to plain text (the flag is undocumented in
`--help`, so treat it as potentially unstable across the rapid release
cadence); keep per-version golden samples.

## Permissions in headless mode

`settings.json` `permissions` (allow/deny/ask over `read_file`,
`write_file`, `read_url`, `command`, `unsandboxed`, `mcp`, ...);
project-dir reads/writes auto-allowed; unconfigured actions default to
**ask**, which stalls headless runs (v1.1.4 made headless honor
settings.json). Orkestra's adapter uses `--mode accept-edits` for
mutating tasks (edit autonomy inside the worktree) and treats
permission stalls as timeouts; `--dangerously-skip-permissions` is only
mapped from Orkestra's explicit `unsafe-full` autonomy mode.

## Live orchestration observations (2026-07-24, agy 1.1.6)

During Orkestra's live smoke runs, `agy -p --mode accept-edits` attempts
reported `status: SUCCESS` **without actually writing the requested
files** into the working directory (deterministic verification failed at
0.0 s; a fallback agent then created them). Interpretation: headless agy
honors its persisted permission policy, and file writes outside what it
auto-allows are silently skipped rather than surfaced as errors. Also
observed once: an empty `response` with `status: SUCCESS` on a review
prompt. Consequences for the adapter/kernel (implemented): agent claims
are never trusted (gates catch silent no-ops), review candidates get a
bounded second round, and users who want agy as a primary implementer
should pre-seed `~/.gemini/antigravity-cli/settings.json`
`permissions.allow` for `write_file`/`command` in their projects.

## Plans and quotas

- Free: weekly-refreshed quota. Google AI Pro: 5-hour refresh + weekly
  cap. Ultra tiers: highest. CLI and IDE share one pool; Flash and Pro
  share a single rate limit. Exact numbers unpublished.
- No API-key auth for agy (Google OAuth only, keyring/browser; print
  mode supports code-paste OAuth).

## Terms of service - flagged prominently

Antigravity Additional ToS: "Using third party software, tools, or
services to access the Service (e.g. using OpenClaw with Antigravity
OAuth) is a breach of this Agreement." The clear target is third-party
harnesses consuming Antigravity OAuth/backends directly. Whether a tool
that merely **launches the unmodified `agy` binary** under the user's
own login is covered is **unresolved** (community forum thread has no
official answer). Google's own docs and codelab clearly contemplate
first-party scripting (`agy -p`, headless OAuth, headless settings
enforcement).

**Orkestra's position:** the adapter only launches the official,
unmodified binary under the user's own login and never touches OAuth
material. Because the gray area is real, Orkestra documents it in the
README and `orkestra doctor` output for the antigravity adapter, so
users can make their own call. This mirrors rule 3 in
`TERMS_AND_AUTHENTICATION_REVIEW.md`.

## Legacy gemini-cli status

Still maintained for enterprise (Apache-2.0), still works with paid
Gemini API keys, Vertex AI auth, and Code Assist Standard/Enterprise
licenses. Only consumer OAuth is cut off → `gemini-cli` remains an
Orkestra adapter, non-default, for those auth modes.

## Sources (retrieved 2026-07-24)

- https://antigravity.google/docs/cli/overview ; /install ; /using ; /features ; /permissions ; /reference ; /plans ; /terms ; /changelog
- https://codelabs.developers.google.com/antigravity-cli-hands-on
- https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
- https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals
- https://github.com/google-antigravity/antigravity-cli (+ issues #7, #76, #318; releases)
- https://github.com/google-gemini/gemini-cli/discussions/27274
- https://discuss.ai.google.dev/t/is-invoking-the-official-antigravity-cli-agy-print-from-a-third-party-developer-tool-an-acceptable-use/175462
- Local verification: `agy --help`, `agy models`, `docs/research/samples/antigravity-*` (2026-07-24)

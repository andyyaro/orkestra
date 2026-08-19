# Agent Integration Research

Retrieved 2026-07-24 from official docs plus local verification against
installed binaries (claude 2.1.219, codex 0.144.4, gemini 0.52.0); local
captures in `samples/`.

## Claude Code (`claude`)

- **Headless:** `claude -p` with `--output-format text|json|stream-json`;
  `stream-json` requires `--verbose` (with `--include-partial-messages`
  for token deltas). Piped stdin capped at 10 MB.
- **JSON envelope** (verified locally): `type:"result"`, `subtype`,
  `is_error`, `result`, `session_id`, `num_turns`, `usage`,
  `total_cost_usd`, `permission_denials`.
- **Stream events:** `system/init` (with `capabilities` array for feature
  detection, v2.1.205+), `assistant`/`user` messages, `stream_event`
  deltas, `system/api_retry` (fields include `error` category enum:
  `authentication_failed`, `rate_limit`, `overloaded`, `billing_error`,
  … - the in-stream rate-limit/auth signal), terminal `result`.
- **Structured output:** `--output-format json --json-schema '<schema>'`
  → validated object in `structured_output`. This is the director
  decision channel.
- **Sessions:** `--session-id <uuid>` to pin; `--resume <id>` (cwd/
  worktree-scoped - resume from the same directory); `--fork-session`.
- **Permissions:** `--permission-mode` (`acceptEdits`, `dontAsk` for
  locked-down automation, `plan`, `bypassPermissions`), `--allowedTools`
  prefix rules, `--add-dir`. No OS sandbox of its own.
- **Exit/errors:** SIGTERM → exit 143; `is_error`/`subtype` in the result
  envelope is the authoritative failure signal.
- **SDK:** `claude-agent-sdk` (Python) wraps the same CLI subprocess;
  works with subscription OAuth. Not adopted for v0.1 to keep one
  uniform subprocess adapter model (ADR-0004); revisit on roadmap.
  Note: `--bare` skips OAuth/keychain (API-key only) - therefore
  Orkestra does **not** use `--bare` under subscription auth; hermetic
  behavior comes from `--setting-sources` and explicit flags.

## Codex CLI (`codex exec`)

- **Headless:** `codex exec --json` → JSONL: `thread.started`
  (`thread_id` = resume handle), `turn.started`,
  `item.started/completed/failed` (items: `agent_message`, reasoning,
  command executions, file changes, MCP calls, plan updates),
  `turn.completed` (usage: `input_tokens`, `cached_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`; no dollar cost), `error`.
  Verified locally.
- **Structured output:** `--output-schema <file>` (JSON Schema for final
  message); validation mismatch = error exit; works with
  `codex exec resume`.
- **Sessions:** `codex exec resume <thread_id>`; `--ephemeral` disables
  persistence/resume.
- **Sandbox (OS-enforced):** `--sandbox read-only|workspace-write|
  danger-full-access` - Apple Seatbelt on macOS, Landlock/seccomp on
  Linux. `exec` defaults to read-only. Network off by default in
  workspace-write. Requires git repo unless `--skip-git-repo-check`.
- **Errors:** non-zero exit on schema mismatch/no-repo; `error` JSONL
  event is the structured failure channel; no published exit-code table.
- **SDK/server:** TS SDK, new Python `openai-codex` SDK (app-server
  JSON-RPC), `codex mcp-server`; app-server marked experimental -
  subprocess `exec` chosen for v0.1.

## Antigravity CLI (`agy`) - first-party Google adapter

Added 2026-07-24 after Google's migration notice: the legacy `gemini`
CLI rejects individual-consumer OAuth ("This client is no longer
supported for Gemini Code Assist for individuals. To continue using
Gemini, please migrate to the Antigravity suite of products."). The
Antigravity CLI (`agy` 1.1.6) is installed and authenticated on this
machine; all findings below verified live (`samples/antigravity-*`).

- **Headless:** `agy -p "<prompt>"` (`--print`); `--print-timeout`
  (default 5m); `--output-format json|stream-json` accepted although
  not listed in `--help` (version-pin and feature-detect in the
  adapter).
- **JSON envelope:** `conversation_id`, `status` (`"SUCCESS"` observed),
  `response`, `duration_seconds`, `num_turns`,
  `usage {input_tokens, output_tokens, thinking_tokens, total_tokens}`.
- **Stream events:** `init` (conversation_id, cwd, tools list,
  `permission_mode: "request-review"`), `step_update`
  (`step_type: user_input|agent_response|checkpoint|unknown`,
  `text_delta`, per-step usage, `state: DONE`), terminal `result`
  (same envelope as json mode).
- **Structured output:** no schema flag → prompt-level JSON with
  bounded repair loop (same strategy as Gemini).
- **Sessions:** `--conversation <id>` resume; `-c/--continue` for most
  recent.
- **Permissions/sandbox:** default `request-review`; `--mode
  accept-edits|plan`; `--dangerously-skip-permissions` (opt-in unsafe);
  `--sandbox` (terminal restrictions); `--add-dir` workspace scoping.
- **Extras:** `--model` (slugs from `agy models`: gemini-3.6-flash-*,
  gemini-3.1-pro-*, claude-sonnet-4-6, gpt-oss-120b-…), `--effort
  low|medium|high`, custom agents via `agent.md`, plugins/MCP.
- **Auth readiness:** `agy models` succeeds only when authenticated -
  a cheap non-invasive readiness probe.

## Gemini CLI (`gemini`) - non-default (API-key / Vertex / Enterprise auth)

- **Headless:** `-p` (or non-TTY); `--output-format json` → envelope
  `{response, stats, error?}`; `stream-json` → JSONL events `init`
  (session id), `message`, `tool_use`, `tool_result`, `error`, `result`.
  Event field schemas are not fully documented - parser is
  version-pinned and defensive.
- **Structured output:** none (no schema flag). Pattern: prompt for raw
  JSON, extract from `response`, validate, bounded repair/retry loop.
- **Sessions:** `--resume <id|latest|index>`, `--list-sessions`
  (project-scoped), `--session-id`.
- **Permissions/sandbox:** `--approval-mode default|auto_edit|yolo|plan`;
  `--sandbox` with Seatbelt profiles (`SEATBELT_PROFILE`) or
  docker/podman container; `--include-directories`; `--skip-trust`.
  `--allowed-tools` deprecated in favor of the Policy Engine.
- **Exit codes (best documented of the three):** 0 success; 1 general/API
  error; 41 auth required (verified locally: JSON error on stderr);
  42 input error; 53 turn limit exceeded.
- **SDK:** TypeScript only (`@google/gemini-cli-sdk`, core lib, ACP
  experimental) - no official Python surface; subprocess is the only
  realistic option.

## Cross-cutting adapter mapping

| Concept | Claude | Codex | Gemini |
|---|---|---|---|
| Session handle | `session_id` | `thread_id` | `init.session_id` |
| Final text | `result` | last `agent_message` item | `response` |
| Usage | `usage` (+`total_cost_usd`) | `turn.completed.usage` | `stats` |
| Failure signal | `is_error`/`subtype`, `api_retry` categories | `error` event, non-zero exit | `error` object, exit 1/41/42/53 |
| Structured final | `--json-schema` | `--output-schema` | prompt + parse + repair |
| Scoped safety | `--permission-mode` + `--allowedTools` + `--add-dir` | `--sandbox` (OS-level) | `--approval-mode` + `--sandbox` |

Resume handles are cwd-scoped for all three → the kernel stores
(session id, cwd) pairs and always resumes from the original directory.

## Recommendation (adopted, ADR-0004)

Uniform subprocess adapters over each CLI's headless mode with
JSONL/JSON normalization; Claude's `--json-schema` powers the director
decision channel; Codex's `--output-schema` powers structured reviews;
Gemini uses prompt-level JSON with a bounded repair loop. SDK/daemon
surfaces (Claude Agent SDK, Codex app-server/MCP, Gemini ACP) recorded
as roadmap candidates.

## Sources (retrieved 2026-07-24)

- https://code.claude.com/docs/en/headless ; https://code.claude.com/docs/en/cli-reference ; https://code.claude.com/docs/en/agent-sdk/python
- https://developers.openai.com/codex/noninteractive ; https://developers.openai.com/codex/cli/reference ; https://developers.openai.com/codex/sdk ; https://github.com/openai/codex/issues/10390
- https://geminicli.com/docs/cli/headless/ ; https://geminicli.com/docs/cli/tutorials/automation/ ; https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/cli-reference.md ; …/sandbox.md ; packages/sdk/README.md
- Local verification: `docs/research/samples/`

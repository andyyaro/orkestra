# Environment Inventory

Recorded: 2026-07-24 (all versions taken from live command output on this machine).

## Host

| Item | Value |
|---|---|
| OS | macOS 26.5.1 (build 25F80) |
| Architecture | arm64 (Apple Silicon) |
| Shell | zsh |

## Core tooling

| Tool | Version | Status |
|---|---|---|
| Git | 2.50.1 (Apple Git-155) | Ready; `user.name` configured |
| GitHub CLI | 2.95.0 | Authenticated to github.com as `andyyaro` (keyring) |
| Docker client | 29.6.1 | Client present; daemon **not running** at session start (Docker Desktop launch attempted) |
| Homebrew | 6.0.11 | Ready |
| Python | 3.14.6 (`/opt/homebrew/bin/python3`) | Ready |
| uv | 0.11.29 (Homebrew build) | Ready |
| Node.js | v25.8.2 | Ready |
| npm | 11.11.1 | Ready |

## Coding agent CLIs

| Agent | Version | Authentication | Headless automation surface (from `--help`) |
|---|---|---|---|
| Claude Code (`claude`) | 2.1.219 | Authenticated (this session runs on it) | `-p/--print` non-interactive; `--output-format text\|json\|stream-json`; `--input-format stream-json`; `--permission-mode acceptEdits\|auto\|bypassPermissions\|manual\|dontAsk\|plan`; `--allowedTools`; `--session-id <uuid>`; `--resume <id>`; `--model`; `--add-dir`; `-w/--worktree` |
| Codex CLI (`codex`) | 0.144.4 | `codex login status` → "Logged in using ChatGPT" | `codex exec [PROMPT]` non-interactive; `--json` (JSONL events on stdout); `--output-schema <FILE>` (JSON Schema for final response); `--output-last-message <FILE>`; `--sandbox read-only\|workspace-write\|danger-full-access`; `-C/--cd <DIR>`; `--add-dir`; `--skip-git-repo-check`; `--ephemeral`; `codex exec resume <id>` |
| Gemini CLI (`gemini`) | 0.52.0 (installed this session via npm) | Not verified non-interactively at inventory time; see `TERMS_AND_AUTHENTICATION_REVIEW.md` | `-p/--prompt` headless; `-o/--output-format text\|json\|stream-json`; `--approval-mode default\|auto_edit\|yolo\|plan`; `-y/--yolo`; `-s/--sandbox`; `--resume`; `--session-id`; `--include-directories` |

## Observations relevant to architecture

- All three agent CLIs expose a non-interactive execution mode with structured
  (JSON or JSONL) output — CLI subprocess integration is viable for all three.
- Codex uniquely supports `--output-schema` for schema-constrained final
  responses. Claude Code supports structured streaming (`stream-json`).
  Gemini supports `--output-format json|stream-json`.
- All three support session resumption in some form (`--resume` /
  `codex exec resume`).
- All three support sandbox/approval controls, which Orkestra's policy layer
  can map onto per-task policies.
- Docker is optional on this machine until the daemon is confirmed running;
  Orkestra treats Docker sandboxing as an opt-in feature with graceful
  degradation.

No credentials, tokens, or secret material were read or recorded.

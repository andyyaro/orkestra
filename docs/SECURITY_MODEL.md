# Security Model

This is the operator-facing summary; the engineering threat model with
per-threat mitigations lives at `security/THREAT_MODEL.md`, and the
disclosure policy at the repository root `SECURITY.md`.

## What Orkestra guarantees

1. **Your branches are never modified.** All agent work happens on
   `ork/<run>/<task>` branches in isolated worktrees; verified results
   accumulate on `ork/<run>/integration`; merging into your branches is
   always a manual step. Pushing is disabled unless you opt in.
2. **Agents cannot self-certify.** Acceptance commands are executed by
   the kernel with exit-code inspection; reviews come from a different
   agent than the implementer, enforced structurally; integration
   requires both.
3. **No shell, no injection.** Every subprocess (agents, git,
   verification) is an argument array; prompts travel as single argv
   elements or stdin; branch and worktree names are kernel-generated
   from a restricted alphabet; verification commands come from your
   config (plan-proposed additions execute only after
   deterministic validation and can only add checks, never replace yours).
4. **Git can't be turned against you.** Orkestra's own git commands run
   with hooks disabled; diffs that touch `.git` internals, hook files,
   `.orkestra`, or `.github/workflows` (configurable) are rejected;
   Orkestra never force-pushes, hard-resets your branches, or deletes
   non-`ork/*` branches.
5. **Credentials stay where they are.** Agents authenticate through
   their own official CLIs. Orkestra never reads token stores, never
   proxies logins, and passes agents an allowlisted environment, not a
   copy of yours.
6. **Secrets don't leak into artifacts.** Everything persisted or
   exported (events, logs, reports) passes credential-shape redaction
   (API keys, tokens, JWTs, PEM blocks, `password=` patterns).
7. **Everything ends.** Retries, review loops, probes, and director
   exchanges are budget-bounded; timeouts kill whole process groups;
   rate-limit signals are backpressure, never retry storms.

## What Orkestra does NOT guarantee

- It cannot make an agent CLI safe *inside* its task. Agents run with
  their vendor's own safety systems in workspace-scoped modes (Claude
  `acceptEdits`, Codex `workspace-write` OS sandbox, Antigravity
  `accept-edits`). What Orkestra controls is what it *accepts from* the
  workspace afterwards: policy-checked diff + gates + review.
- Prompt injection in your repository can influence what an agent
  writes. Defense in depth means injected text still cannot expand
  permissions, skip gates, dodge review, or escape the worktree - but
  review quality matters; keep `require_review = true`.
- Local processes with your OS account can read `.orkestra/` state
  (task transcripts of your own project). No secrets are stored there,
  and exports are redacted.

## Elevated modes (explicit, never default)

| Setting | Effect | Named risk |
|---|---|---|
| `agents.<x>.autonomy = "unsafe-full"` | Maps to the vendor CLI's own bypass mode (`bypassPermissions` / `danger-full-access` / `--dangerously-skip-permissions`) | The agent can act outside the worktree within that CLI's power; use only in disposable environments |
| `policy.require_review = false` | Skips the independent review gate | Single-agent blind spots go uninspected |
| `policy.allow_push = true` | Permits pushing | Outbound effects beyond your machine |

Every elevated setting is visible in config review, in `doctor` output,
and in the run report.

## Reporting vulnerabilities

See `SECURITY.md` (private disclosure via GitHub security advisories).

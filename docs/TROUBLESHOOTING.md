# Troubleshooting

## `orkestra doctor` says an agent is "auth needed"

Sign in with the vendor's own flow, then re-run doctor:

- Claude Code: run `claude` once interactively (or `claude setup-token`
  for headless environments).
- Codex: `codex login` (`codex login status` to confirm).
- Antigravity: run `agy` once; it signs in via keyring/browser.
- Gemini CLI: export `GEMINI_API_KEY` (consumer Google OAuth is no
  longer served by this CLI — use the Antigravity agent instead).

## "repository has uncommitted changes"

Orkestra refuses to start runs on a dirty repo so it can never entangle
your work with agent work. `git status`, then commit or stash. Note that
untracked files count — including logs you redirect into the repo.

## "at least two enabled agents are required"

Orkestra is a multi-agent orchestrator by design. Enable a second agent
in `.orkestra/config.toml` — the `fake` adapter works for trying the
machinery without quota.

## A task is `blocked` / the run says `waiting_human`

That's a human gate, not a crash. `orkestra decisions` shows the
question, options, and recommendation; `orkestra approve <id> --option
<key>` then `orkestra resume`.

## The run was interrupted (Ctrl-C, crash, reboot)

State is persistent. `orkestra resume` reconciles (closes dangling
attempts, repairs worktrees) and continues. Nothing is executed twice;
interrupted attempts are re-planned cleanly.

## Verification keeps failing

The kernel runs your `verify.commands` inside the task worktree with an
allowlisted environment. Check they pass in a fresh checkout
(`git worktree add /tmp/wt <branch> && cd /tmp/wt && <command>`), and
remember agents may need the command's tools available on PATH.

## Merge conflicts between tasks

Normal under parallelism: the kernel aborts the conflicted merge,
recreates the task's workspace from the updated integration branch, and
re-runs the task. If it loops, your task decomposition has two tasks
editing the same files — restructure the spec or lower
`max_concurrency`.

## Rate limits

Rate-limited agents back off (60 s base, exponential) and eventually
fall back to other agents or a human gate. Long runs on subscription
plans may simply need to wait for your provider's window to reset —
`orkestra pause` / `resume` are safe across resets.

## Antigravity task stalls until timeout

Headless `agy` honors its own `settings.json` permissions; unconfigured
actions default to "ask", which cannot be answered in print mode.
Pre-approve what your tasks need in `~/.gemini/antigravity-cli/
settings.json` (`permissions.allow`), or accept edit-only autonomy.

## Where is everything?

- State DB: `.orkestra/orkestra.db` (SQLite; delete to reset project)
- Worktrees: `.orkestra/worktrees/` (auto-cleaned; preserved on failure)
- Run branches: `git branch --list 'ork/*'`
- Events/log: `orkestra logs`; full export: `orkestra report --json-out`

## Reporting bugs

`orkestra report --out report.md --json-out report.json` produces
redacted artifacts safe to attach to an issue.

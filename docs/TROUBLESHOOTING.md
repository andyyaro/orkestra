# Troubleshooting

## `orkestra doctor` says an agent is "auth needed"

Sign in with the vendor's own flow, then re-run doctor:

- Claude Code: run `claude` once interactively (or `claude setup-token`
  for headless environments).
- Codex: `codex login` (`codex login status` to confirm).
- Antigravity: run `agy` once; it signs in via keyring/browser.
- Gemini CLI: export `GEMINI_API_KEY` (consumer Google OAuth is no
  longer served by this CLI — use the Antigravity agent instead).

## "this folder is inside an existing Git repository"

`orkestra start`/`init` set up a project with its own repository; in a
subdirectory of an existing repo, git would resolve everything to the
parent project. Run the command at that repository's root, or create
the project outside it. Nothing was changed.

## "repository has uncommitted changes"

Orkestra refuses to start runs while tracked files have uncommitted
edits (staged or not), so it can never entangle your work with agent
work. `git status`, then commit or stash. Untracked files don't block a
run — Orkestra simply never touches them (`orkestra accept` refuses if
a result would overwrite one). This includes SPEC.md: if you edit it
after setup, commit the edit before `orkestra run`.

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
interrupted attempts are re-planned cleanly. An interrupt that landed
*before* planning finished is re-planned from your spec as a fresh run.

## Verification keeps failing

The kernel runs your `verify.commands` inside the task worktree with an
allowlisted environment. Check they pass in a fresh checkout
(`git worktree add /tmp/wt <branch> && cd /tmp/wt && <command>`), and
remember agents may need the command's tools available on PATH. The
failing command's output is shown in the event log and handed to the
agent that repairs the work, so `orkestra logs` tells you why.

A command that cannot even start (missing executable, unparsable) is
caught *before* any agent runs and blocks the task: fix
`.orkestra/config.toml` first — retrying without editing it fails
identically.

## "ignoring plan acceptance entry"

The plan proposed an extra per-task check that isn't a runnable command
(prose, or shell syntax like pipes — commands run without a shell). It
is dropped, not executed. Your `[verify]` commands still gate the task,
so this is informational.

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

## An agent says it needs permission to run commands

Headless agents cannot answer permission prompts. Claude Code runs with
`--permission-mode acceptEdits`, so it edits files freely but cannot
*run* commands (like your test suite). Since v0.5.2 the task brief tells
the agent this up front so it doesn't waste turns asking, and Orkestra
surfaces a warning if it asks anyway. Set `run_commands = true` on an
agent to let it run commands in its own worktree. It is not fatal — Orkestra runs
your `[verify]` commands itself, deterministically, after the agent
finishes. To let agents run commands themselves, pre-approve the tools
they need in the vendor CLI's own settings (e.g. Claude Code's
`~/.claude/settings.json` `permissions.allow`).

## Antigravity task stalls until timeout

Headless `agy` honors its own `settings.json` permissions; unconfigured
actions default to "ask", which cannot be answered in print mode.
Pre-approve what your tasks need in `~/.gemini/antigravity-cli/
settings.json` (`permissions.allow`), or accept edit-only autonomy.

## Where is everything?

- State DB: `.orkestra/orkestra.db` (SQLite; delete to reset project)
- Worktrees: `.orkestra/worktrees/` (auto-cleaned; preserved on failure)
- Run branches (advanced): `git branch --list 'ork/*'` — normally you
  only need `orkestra review` / `orkestra accept`
- Events/log: `orkestra logs`; full export: `orkestra report --json-out`

## Reporting bugs

`orkestra report --save` writes redacted markdown + JSON under
`.orkestra/reports/` (git-ignored), safe to attach to an issue;
`--out`/`--json-out` write to explicit paths instead.

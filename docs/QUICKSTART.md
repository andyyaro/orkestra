# Quickstart

Ten minutes from empty directory to a verified, multi-agent result.

## 0. Watch it work first (free)

```bash
orkestra demo
```

Scripted fake agents, real engine: planning, parallel isolated tasks,
a review rejection and repair, integration. No quota, no logins.

## 1. One command

```bash
mkdir hello-orkestra && cd hello-orkestra
orkestra start
```

The wizard finds your agents, offers a preset (Faster / Balanced /
Maximum quality / Custom with per-agent models and effort), confirms
the verification commands it detected, helps you write SPEC.md, and
offers to run immediately. Everything below is the manual route the
wizard automates — useful for scripting (`orkestra start
--non-interactive --preset balanced`) and for understanding the pieces.

## 1b. Manual: initialize

```bash
orkestra init .
```

This creates a Git repo (if needed), `.orkestra/config.toml`, a `SPEC.md`
template, and gitignores Orkestra's local state.

## 2. Describe the work

Edit `SPEC.md`:

```markdown
# hello-orkestra

Create `greet.py` with a function `greet(name: str) -> str` returning
exactly `Hello, {name}!`, plus `test_greet.py` runnable with
`python3 test_greet.py`, and a short USAGE.md.
```

## 3. Configure agents and gates

`orkestra init` already enabled the agent CLIs it found on your PATH
**and pre-filled `[verify]` commands from your project's test setup**
(pytest/npm/cargo/go). Check them — they are the safety net agents
cannot talk past. Optionally pick models and effort:

```bash
orkestra agents set claude --model sonnet
orkestra agents set antigravity --effort high
```

Commit your spec (Orkestra refuses to run while tracked files have uncommitted edits (untracked files don't block)):

```bash
git add -A && git commit -m "spec"
```

## 4. Check readiness

```bash
orkestra doctor
```

Fix anything red (usually: sign in to an agent CLI with its own login
command).

## 5. Run

```bash
orkestra run
```

Watch the phases: director analysis → capability probes → plan (with
challenges from the other agents) → tasks executing in isolated
worktrees → verification → cross-agent review → integration.

Useful while it runs (from another terminal):

```bash
orkestra status
orkestra logs --limit 50
orkestra pause     # finish in-flight tasks, then stop
orkestra resume
```

## 6. Review and accept

```bash
orkestra review              # what was built: status, checks, changes
orkestra review --full       # the whole patch
orkestra accept --cleanup    # bring it into your branch (asks first), tidy up
orkestra report --out report.md
```

(`diff` and `merge` still work as advanced aliases.)

## If it stops with a question

```bash
orkestra decisions   # what happened + a plain-language explanation
orkestra approve     # picks the open decision and prompts you
orkestra resume
```

## Try it without spending any quota

```bash
orkestra plan --offline     # heuristic planning, no LLM calls
orkestra run --offline      # only meaningful with fake/external agents
```

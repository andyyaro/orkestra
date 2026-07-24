# Quickstart

Ten minutes from empty directory to a verified, multi-agent result.

## 1. Initialize

```bash
mkdir hello-orkestra && cd hello-orkestra
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

`orkestra init` already enabled the agent CLIs it found on your PATH.
Open `.orkestra/config.toml`, confirm at least two agents are enabled,
and add a deterministic acceptance command:

```toml
[verify]
commands = ["python3 test_greet.py"]
```

Commit your spec (Orkestra refuses to run on a dirty repo):

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

## 6. Inspect and merge

```bash
orkestra report --out report.md
git log --oneline ork/<run-id>/integration
git merge ork/<run-id>/integration     # when you're satisfied
```

## If it stops with a question

```bash
orkestra decisions          # what, why, options, recommendation
orkestra approve dec_xxxx --option retry
orkestra resume
```

## Try it without spending any quota

```bash
orkestra plan --offline     # heuristic planning, no LLM calls
orkestra run --offline      # only meaningful with fake/external agents
```

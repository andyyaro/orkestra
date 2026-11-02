# Orkestra launch film: every claim and its source

The narration as written is `narration/lines.json`; what is on screen is in `compositions/`. Paths
below are in this repository unless they say otherwise. The film was made against Orkestra 0.5.5
(`pyproject.toml`) on 2026-11-01.

## Narration

| Line | Claim | Source |
|---|---|---|
| v01–v02 | "You already use coding agents. Claude Code. Codex. Antigravity." | The README's opening and its "Supported agents" table: `claude-code`, `codex-cli`, `antigravity-cli` |
| v03–v04 | "One at a time is slow. All at once is chaos." | The film's framing of the problem, not a measured claim |
| v06 | "Many coding agents. One repo. Nothing lands unreviewed." | README: "two or more of them work on the same project at once … nothing lands until a *different* agent has reviewed it" |
| v07 | "A director plans the work, and every task runs in its own Git worktree." | README, "How it works": the director agent decomposes the work; "every task runs in its own isolated Git worktree" |
| v08 | "Your tests are the referee." | README: "your test commands are the referee"; the kernel runs your `[verify]` commands and reads exit codes itself |
| v09 | "And a different agent reviews every change before it lands." | README, "What you can rely on": implementer ≠ reviewer, kernel-enforced; `src/orkestra/policy/engine.py` rejects a reviewer who is the implementer |
| v10 | "Changes requested? It repairs, and tries again. But never forever." | `orkestra demo` output: a rejection, a repair loop, "bounded - never spins forever"; `max_review_cycles` defaults to 2 (`src/orkestra/schemas/config.py`) |
| v11 | "Your branches are never touched." | README: "Your branches are never modified"; `orkestra accept` is the only step that touches your branch, and it asks first |
| v12 | "Five hundred and fifty-seven tests." | `pytest --collect-only` collected 557 on 0.5.5, and the full suite passed on 2026-11-01. The README states the same count, and `tests/unit/test_readme_claims.py` keeps it equal to what pytest collects |
| v12 | "Crash-safe resume. Secrets redacted." | README, "What you can rely on": SQLite state and idempotent transitions, `orkestra resume`; credential-shape redaction on everything persisted or exported (`src/orkestra/redact.py`) |
| v13 | "Open source, on GitHub and PyPI." | Apache-2.0 (`LICENSE`); github.com/andyyaro/orkestra; PyPI package `orkestra-runtime` (`pyproject.toml`) |
| v14 | "See it in sixty seconds, for free." | README, "See it in 60 seconds - free": `orkestra demo` uses scripted fake agents, "no agent CLIs, no logins, no tokens spent" |

## On screen

| Scene | What is shown | Source |
|---|---|---|
| Meet | The `orkestra watch` window: run `run_522f70d8`, project `orkestra-demo`, tasks feature-a, feature-b and docs, their states, primary agents and reviewers, and the event lines | The run of `orkestra demo` the film was made from; the agents are the demo's fake agents ada and grace |
| How it works | The plan line, the worktree branches `ork/run_522f70d8/task_345016e8` and `…/task_181d0f78`, the gate `python check_demo.py` passing with exit 0 | The same run; branch names follow `ork/{run_id}/{task_id}` (`src/orkestra/ids.py`); the gate is the demo's own (`src/orkestra/cli/demo.py`) |
| How it works | ada's diff of `feature_a.py` and grace's verdict: `"approve": false`, "demo reviewer wants a docstring", severity medium | The demo's scripted reviewer (`FAKE:reject_once:demo reviewer wants a docstring` in `src/orkestra/cli/demo.py`) |
| Repair | The log of the repair, ending "task feature-a done, landed as 2d63c4c"; the chip `max_review_cycles = 2` | The same run; the default in `src/orkestra/schemas/config.py` |
| Safe | "starting point: your code as of commit 72b8c61 (nothing of yours has been changed)" | The wording of `orkestra review` (`src/orkestra/cli/main.py`), which prints 10 characters of the run's starting commit; the film shows 7 |
| Proof | 557 "tests, all passing", "pytest, Orkestra v0.5.5" | As v12 above |
| Proof | `GITHUB_TOKEN=ghp_…` turning into `[REDACTED]` | `[REDACTED]` is the marker in `src/orkestra/redact.py`. The token is fake. Run through `redact()`, the whole assignment becomes `[REDACTED]`; the film keeps the variable's name so the swap reads |
| Open source | github.com/andyyaro/orkestra, `pypi: orkestra-runtime`, `apache-2.0 · v0.5.5` | `pyproject.toml`, `LICENSE` |
| Try it | `orkestra demo` and five of its output lines, long lines trimmed | A real run of `orkestra demo` on 0.5.5, 2026-11-01 (noted in `compositions/code-terminal-run.html`) |
| Try it | "No agent CLIs. No logins. No tokens spent." | README |
| End card | `uv tool install 'orkestra-runtime[tui]'` | README, "See it in 60 seconds - free" |

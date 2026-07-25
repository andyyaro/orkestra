# FAQ

**Why does Orkestra require at least two agents?**
Independent review is the core quality mechanism: the agent that wrote
the code never approves it. With one agent that guarantee is impossible,
and single-agent workflows are already well served by each vendor's own
CLI.

**Does it cost me API money?**
No API keys are required or used by default. Agents run under your
existing CLI subscriptions (Claude, ChatGPT, Google plans); Orkestra
treats their rate limits as backpressure and never opts you into paid
overflow. The optional `gemini-cli` adapter is the exception — it needs
a `GEMINI_API_KEY` or Vertex setup you provision.

**Will parallel agents burn through my plan limits?**
Faster than serial use, yes — that's physics. Defaults are conservative
(`max_concurrency = 2`, probes cached and budgeted). Usage per agent is
recorded and shown in `orkestra report`.

**Can Claude assign work to itself?**
Yes. The director is a planner, not a bystander — Claude (or whichever
agent directs) appears in the candidate pool like everyone else, and the
kernel only enforces that the reviewer of any task differs from its
implementer.

**Can I use a different director than Claude?**
Yes — `director.agent` may point at any enabled agent. Structured-output
support makes a director effective; without it Orkestra falls back to
the deterministic heuristic planner (also used by `--offline`).

**What happens if I close my laptop mid-run?**
State is in SQLite with idempotent transitions. `orkestra resume`
reconciles (dangling attempts marked interrupted, worktrees repaired)
and continues. Nothing is silently executed twice.

**Where does the result end up?**
In a holding area your branches never see until you act: `orkestra
review` shows it, `orkestra accept` brings it into your branch (after a
confirmation, and only for completed runs). Under the hood it's a Git
branch (`ork/<run>/integration`) — visible to advanced users, never
required knowledge.

**Why did my run stop with a question?**
Budgets exhausted, a policy wall, or missing auth — cases with genuinely
different valid answers. `orkestra decisions` explains; unblocked tasks
keep running meanwhile.

**Is my repository content sent anywhere?**
Orkestra itself makes zero network calls. The agent CLIs you enable send
context to their providers under your accounts, exactly as they do when
you use them directly — review each provider's data terms
(`docs/PROVIDERS.md`).

**Can agents see each other's work in progress?**
No. Each task runs in an isolated worktree. Agents see completed,
integrated results of dependency tasks (their worktree branches from the
integration head), never half-done parallel work.

**Does it work on Windows?**
Untested; process-group and worktree semantics differ. Roadmap item.

**How do I add my own agent?**
Speak the tiny `orkestra-jsonl/1` protocol from any language and declare
it in config: `docs/adapters/PROTOCOL.md`.

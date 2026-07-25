# Authoring an Agent Adapter

Two integration paths exist:

1. **External command** (recommended, no Python required): implement the
   `orkestra-jsonl/1` protocol — see `PROTOCOL.md`. This is how you ship
   an adapter today without touching Orkestra's codebase.
2. **Built-in adapter** (contribution to Orkestra): subclass
   `orkestra.adapters.base.AgentAdapter` and register it in
   `src/orkestra/adapters/registry.py`.

## Built-in adapter contract

```python
class AgentAdapter(ABC):
    adapter_id: str  # stable slug, e.g. "my-cli"
    executable: str  # binary name looked up on PATH

    async def detect(self) -> AdapterInfo: ...
    async def check_auth(self) -> AuthStatus: ...
    def build_invocation(self, brief: TaskBrief) -> InvocationSpec: ...
    def make_parser(self, brief: TaskBrief) -> StreamParser: ...
```

Design rules, learned from the first-party adapters:

- **Never construct shell strings.** `InvocationSpec.argv` is an argument
  array; prompts travel as a single argv element or via `stdin_data`.
- **Never read credential stores.** `check_auth()` must use the CLI's own
  status surface (e.g. `codex login status`) or a cheap authenticated
  no-quota command (e.g. `agy models`), or defer to runtime detection.
- **Parse defensively.** Real CLIs interleave banners and warnings with
  JSON. Use `orkestra.adapters.jsonl.try_parse_json` per line, keep a
  stderr tail for error classification, and always return a result even
  for garbage input (`ErrorKind.INVALID_OUTPUT`, never an exception).
- **Classify errors into the closed taxonomy** (`ErrorKind`); `auth` and
  `rate_limit` drive fallback/backoff behavior, so accuracy matters.
- **Feature-flag capabilities** in `AdapterInfo.features` — e.g.
  `structured_output`, `resume`, `stream`, `os_sandbox`,
  `structured_director`. The kernel adapts (a director needs
  `structured_director` or the run falls back to heuristic planning).
- **Map Orkestra autonomy to the CLI's own safety system**: the explicit
  `unsafe-full` autonomy maps to the CLI's bypass flag and nothing else
  does; for `research`/`plan`/`review` task kinds prefer the CLI's
  read-only or plan mode where it has one (codex, gemini and antigravity
  adapters do this; Claude Code has no read-only mode); otherwise confine
  edits to the workspace (`--permission-mode acceptEdits`,
  `--sandbox workspace-write`, `--mode accept-edits`, …).
- **Surface permission stalls instead of hanging.** A headless CLI that
  asks for approval it cannot receive should emit an `EventKind.WARNING`
  (see `_PERMISSION_MARKERS` in the Claude Code adapter) rather than
  waiting for the task timeout.
- **Version-pin expectations.** Capture golden output samples (see
  `docs/research/samples/`) and unit-test your parser against them, plus
  rate-limit/auth/garbage cases.

## Testing

- Parser goldens: follow `tests/adapters/test_parsers.py`.
- Process behavior: run the contract kit against a scriptable stand-in
  (`orkestra.adapters.testkit.run_contract_suite`).
- End-to-end: add your adapter to a fake-agent config in
  `tests/e2e/conftest.py` style tests if contributing upstream.

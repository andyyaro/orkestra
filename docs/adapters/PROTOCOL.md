# External Adapter Protocol — `orkestra-jsonl/1`

Third-party agents integrate with Orkestra as **external commands**
declared explicitly in project configuration (no dynamic code loading;
see ADR-0006). Any language works — the reference implementation is
`orkestra/adapters/fake_worker.py`.

## Declaration

```toml
[agents.myagent]
adapter = "external"
command = ["/usr/local/bin/my-agent", "--headless"]
```

## Detection handshake

Orkestra runs your command with the extra argument `--orkestra-detect`.
Respond on stdout with one JSON line and exit 0:

```json
{"protocol": "orkestra-jsonl/1", "version": "1.2.0", "name": "my-agent"}
```

## Task invocation

For each attempt, Orkestra runs your command with:

- **stdin**: the task brief as one JSON document:

```json
{
  "task_id": "task_3f9a1c2b",
  "run_id": "run_a1b2c3d4",
  "title": "Implement the parser",
  "kind": "implement",
  "instructions": "…full rendered brief…",
  "cwd": "/path/to/isolated/worktree",
  "timeout_s": 1800,
  "effort": null,
  "json_schema": null,
  "resume_session_id": null
}
```

- **cwd**: the isolated Git worktree. Mutate files only under this
  directory. Do **not** run `git commit`/`push` — the kernel commits
  deterministically after your process exits.

## Output events (stdout, one JSON object per line)

| Event | Required | Shape |
|---|---|---|
| `started` | no | `{"type": "started", "session_id": "…"}` |
| `text` | no | `{"type": "text", "text": "progress note"}` |
| `tool` | no | `{"type": "tool", "name": "write:src/x.py"}` |
| `result` | **yes, terminal** | see below |

```json
{
  "type": "result",
  "status": "ok",
  "final_text": "summary of what was done",
  "structured": null,
  "error_kind": "none",
  "error_detail": "",
  "usage": {"input_tokens": 0, "output_tokens": 0,
            "cached_input_tokens": 0, "total_cost_usd": null}
}
```

- `status`: `"ok"` or `"error"`.
- `error_kind` (on error): one of `auth`, `rate_limit`, `timeout`,
  `cancelled`, `crash`, `invalid_output`, `policy`, `unavailable`,
  `unknown`. Use `auth` and `rate_limit` accurately — they drive
  fallback and backoff decisions.
- `structured`: when the brief carries a non-null `json_schema`, put the
  schema-conforming JSON object here (reviews expect a verdict object:
  `{"schema_version": 1, "approve": bool, "findings": [...],
  "required_changes": [...], "severity": "none|low|medium|high|critical"}`).

## Rules enforced around you

- Missing `result` event → the attempt is recorded as `invalid_output`.
- Wall-clock timeout → your whole process group receives SIGTERM, then
  SIGKILL after 5 s. Handle SIGTERM if you need cleanup.
- Everything you print is redacted for credential shapes before being
  persisted.
- Diffs touching `.git`, Git hooks, `.orkestra`, or configured protected
  paths cause the attempt to be rejected by policy.

## Compliance testing

```python
import asyncio
from pathlib import Path
from orkestra.adapters.external import ExternalAdapter
from orkestra.adapters.testkit import run_contract_suite

adapter = ExternalAdapter(command=["/usr/local/bin/my-agent", "--headless"])
report = asyncio.run(run_contract_suite(adapter, Path("/tmp/contract")))
print(report.summary())
assert report.passed
```

The suite exercises: detection, happy path, error results, non-zero
exits, garbage output tolerance, missing results, timeout enforcement,
cancellation, and structured output. Note: scenarios are driven by
`FAKE:` directives in the instructions — a real agent binary should be
pointed at the suite only via a scripting shim that honors them, or you
can adapt the scenarios from `tests/adapters/test_contract.py`.

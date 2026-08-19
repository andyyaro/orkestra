# Contributing to Orkestra

Thanks for your interest in improving Orkestra.

## Development setup

Requirements: Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), Git.

```bash
git clone https://github.com/andyyaro/orkestra
cd orkestra
uv sync            # creates .venv with dev dependencies
uv run pytest      # run the test suite
```

## Quality gates (run before every PR)

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=orkestra
uv run bandit -c pyproject.toml -r src
```

CI runs the same commands; PRs must be green.

## Ground rules

- **Determinism first.** The kernel must never depend on LLM output for
  policy, state transitions, or verification. Director/agent output is
  untrusted input - validate it.
- **No fixed-agent-count assumptions.** Code, schemas, and tests must work
  for 2 agents and for N agents. Never hard-code three.
- **Security posture.** Subprocesses use argument arrays (no `shell=True`);
  external paths are resolved and scope-checked; Git runs hook-disabled;
  secrets are redacted from anything persisted.
- **Evidence over self-report.** New agent-facing behavior needs a fake- or
  contract-test demonstrating the failure modes (timeout, garbage output,
  non-zero exit), not just the happy path.
- **Tests accompany code.** Bug fixes include a regression test.

## Adding an agent adapter

See `docs/adapters/AUTHORING.md`. Implement the adapter contract, then run
the contract test kit:

```bash
uv run pytest tests/adapters/test_contract.py  # see docs/adapters/PROTOCOL.md
# ("Compliance testing") for wiring the suite to your own adapter
```

## Commit / PR conventions

- Small, atomic commits with imperative subjects.
- PRs describe *what* and *why*; link issues.
- ADRs (`docs/architecture/adr/`) for decisions that constrain future work.

## Code of conduct

See `CODE_OF_CONDUCT.md`. Be excellent to each other.

## License

Contributions are accepted under Apache-2.0 (inbound = outbound, per
Apache-2.0 §5). No CLA.

# What & why

<!-- One paragraph: what changes, and what problem it solves. -->

## Checklist

- [ ] Tests accompany the change (bug fixes include a regression test)
- [ ] `uv run ruff format --check . && uv run ruff check .` pass
- [ ] `uv run mypy` passes (strict)
- [ ] `uv run pytest` passes
- [ ] No fixed-agent-count assumptions introduced (works for 2 and N agents)
- [ ] Kernel determinism preserved (no LLM output used for policy,
      state transitions, or verification)
- [ ] New subprocess calls use argv arrays, never shell strings
- [ ] Anything persisted or exported passes through redaction

## Notes for the reviewer

<!-- Risky areas, alternatives considered, follow-ups deferred. -->

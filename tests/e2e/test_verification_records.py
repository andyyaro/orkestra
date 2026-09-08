"""The ``verifications`` table must agree with what actually happened.

These tests do not check that rows exist. They re-derive every fact from
an independent source (the emitted event text, and git itself) and
require the stored row to match it, because a verification record that
disagrees with the run it describes is worse than no record at all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from orkestra.app import App, build_app
from orkestra.schemas.common import RunState
from orkestra.verify.record import BINDING_NOT_CHECKED, BINDING_PROVED, SCOPE_TASK
from orkestra.workspace.git import GitRepo
from tests.e2e.conftest import make_project
from tests.e2e.test_orchestration import assign, manual_run, spec

#: The exact shape VerificationOutcome.summary renders into the event.
_SUMMARY_LINE = re.compile(r"^(PASS|FAIL) \(exit (-?\d+), ([\d.]+)s\): (.+)$")


def _set_verify(app: App, commands: list[str], *, binding_check: bool = False) -> App:
    """Configure the gate.

    The binding canary defaults OFF here, on purpose. Most tests in this file
    are about what gets recorded, not about binding, and leaving a global
    default to drift through them makes their assertions mean something other
    than what they say. The tests that are about binding turn it on.
    """
    config_path = app.root / ".orkestra" / "config.toml"
    rendered = ", ".join(f'"{c}"' for c in commands)
    config_path.write_text(
        config_path.read_text()
        + f"\n[verify]\ncommands = [{rendered}]\nbinding_check = {str(binding_check).lower()}\n"
    )
    app.close()
    return build_app(app.root, offline=True)


def _summary_lines(app: App, run_id: str) -> list[tuple[str, int, str, str]]:
    """(PASS/FAIL, exit code, duration to 1dp, command) from the events."""
    parsed = []
    for event in app.store.events_for_run(run_id, limit=1000):
        text = str(event["text"])
        if not text.startswith("verification "):
            continue
        for line in text.splitlines():
            match = _SUMMARY_LINE.match(line.strip())
            if match:
                parsed.append((match.group(1), int(match.group(2)), match.group(3), match.group(4)))
    return parsed


async def _commit_gate_scripts(root: Path, scripts: dict[str, str]) -> None:
    """Gate scripts must be committed: the gate runs in the task worktree,
    which only ever contains committed files."""
    for name, body in scripts.items():
        (root / name).write_text(body)
    await GitRepo(root).add_all_and_commit("add gate scripts")


class TestVerificationRecordsMatchTheRun:
    async def test_stored_exit_codes_and_durations_match_the_events(self, tmp_path: Path) -> None:
        base = await make_project(tmp_path)
        # A measurable sleep: a duration that is always 0.0 would let a
        # hardcoded zero pass this test.
        await _commit_gate_scripts(base.root, {"slow.py": "import time\ntime.sleep(0.35)\n"})
        app = _set_verify(base, ["python3 slow.py", "true"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            state = await app.orchestrator.execute(run_id)
            assert state is RunState.COMPLETE

            rows = app.store.verifications_for_run(run_id)
            events = _summary_lines(app, run_id)
            print(f"event summary lines: {events}")
            print(
                "stored rows: "
                + str(
                    [
                        (r.scope, r.command, r.exit_code, round(r.duration_s, 3), r.binding)
                        for r in rows
                    ]
                )
            )
            assert len(events) == 2, events
            assert len(rows) == len(events)

            # Every executed command, in order, with the same verdict, the
            # same exit code and the same duration the event reported.
            from_rows = [
                ("PASS" if r.passed else "FAIL", r.exit_code, f"{r.duration_s:.1f}", r.command)
                for r in rows
            ]
            assert from_rows == events

            slow, fast = rows
            assert slow.command == "python3 slow.py"
            assert slow.duration_s >= 0.35, slow.duration_s
            assert fast.command == "true"
            # The sleep really is the slow one: the durations are measured,
            # not copied from a single shared value.
            assert slow.duration_s > fast.duration_s
            assert slow.argv == ["python3", "slow.py"]
            assert fast.argv == ["true"]
        finally:
            app.close()

    async def test_recorded_tree_is_the_tree_that_was_verified(self, tmp_path: Path) -> None:
        base = await make_project(tmp_path)
        app = _set_verify(base, ["true"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:proof.txt:contents"), assign("alpha", "beta"))]
            )
            assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
            row = app.store.verifications_for_run(run_id)[0]
            repo = GitRepo(app.root)

            # The commit sha is checkoutable and its tree is the recorded one.
            derived_tree = await repo.rev_parse(f"{row.commit_sha}^{{tree}}")
            print(f"commit={row.commit_sha} tree={row.tree_sha} derived={derived_tree}")
            assert derived_tree == row.tree_sha

            # And that tree is the agent's work, not the base tree.
            _, listing, _ = await repo._git("ls-tree", "-r", "--name-only", row.tree_sha)
            print(f"tree contents: {listing.split()}")
            assert "proof.txt" in listing.split()
            base_tree = await repo.rev_parse(f"{app.store.get_run(run_id).base_commit}^{{tree}}")
            assert row.tree_sha != base_tree

            assert row.scope == SCOPE_TASK
            assert row.task_id == app.store.tasks_for_run(run_id)[0].task_id
            assert row.binding == BINDING_NOT_CHECKED
            assert row.env_fingerprint.startswith("sha256:")
            assert row.output_digest.startswith("sha256:")
        finally:
            app.close()

    async def test_only_executed_commands_are_recorded(self, tmp_path: Path) -> None:
        base = await make_project(tmp_path)
        await _commit_gate_scripts(base.root, {"boom.py": "import sys\nsys.exit(3)\n"})
        # run_verification stops at the first failure, so the second command
        # never runs and must not appear as evidence that it did.
        app = _set_verify(base, ["python3 boom.py", "true"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            await app.orchestrator.execute(run_id)
            rows = app.store.verifications_for_run(run_id)
            commands = [r.command for r in rows]
            exits = [r.exit_code for r in rows]
            print(f"recorded commands={commands} exits={exits}")
            assert rows, "the failing gate ran, so it must have been recorded"
            assert set(commands) == {"python3 boom.py"}
            assert set(exits) == {3}
            # Same failing gate on every retry, one row each, never "true".
            assert len(rows) == len(_summary_lines(app, run_id))

            summary = app.store.verification_summary(run_id)
            print(f"summary: {summary}")
            assert len(summary) == 1
            assert summary[0]["scope"] == SCOPE_TASK
            assert summary[0]["binding"] == BINDING_NOT_CHECKED
            assert summary[0]["n"] == len(rows)
            assert summary[0]["passed"] == 0
            assert summary[0]["duration_s"] == pytest.approx(sum(r.duration_s for r in rows))
        finally:
            app.close()

    async def test_executable_is_resolved_to_a_real_path(self, tmp_path: Path) -> None:
        base = await make_project(tmp_path)
        app = _set_verify(base, ["python3 -c pass"])
        try:
            run_id = await manual_run(
                app, [(spec("t", "FAKE:write:a.txt:x"), assign("alpha", "beta"))]
            )
            assert await app.orchestrator.execute(run_id) is RunState.COMPLETE
            row = app.store.verifications_for_run(run_id)[0]
            print(f"exe_realpath={row.exe_realpath!r} exe_version={row.exe_version!r}")
            # An exit code is a statement about a binary, not about a name.
            assert Path(row.exe_realpath).is_absolute()
            assert Path(row.exe_realpath).exists()
            assert row.exe_version.lower().startswith("python")
        finally:
            app.close()


class TestBindingProofReachesTheRecord:
    """The row must carry the canary's verdict, not a standing default.

    This is the whole point of the binding work: an exit code is evidence
    about a tree only if the command read that tree, so the record has to
    say which. The canary and the column shipped in separate changes and
    were not joined, so every row said `not_checked` while the same run's
    event said BOUND. Correct events, inert feature.
    """

    async def test_a_proved_gate_is_recorded_as_proved(self, tmp_path: Path) -> None:
        app = await make_project(tmp_path)
        (app.root / "seed.py").write_text("VALUE = 1\n")
        # A file, not an inline -c: quoting a Python one-liner inside TOML
        # inside an f-string is how you get a config that does not parse.
        (app.root / "check.py").write_text(
            "import ast, pathlib\n"
            "for path in pathlib.Path().glob('*.py'):\n"
            "    ast.parse(path.read_text())\n"
        )
        await GitRepo(app.root).add_all_and_commit("checker")
        config_path = app.root / ".orkestra" / "config.toml"
        config_path.write_text(
            config_path.read_text()
            + f'\n[verify]\ncommands = ["{sys.executable} check.py"]\nbinding_check = true\n'
        )
        app.close()
        app = build_app(app.root, offline=True)
        try:
            run_id = await manual_run(
                app,
                [(spec("t", "FAKE:write:mod.py:def f():\\n    return 1"), assign("alpha", "beta"))],
            )
            await app.orchestrator.execute(run_id)
            rows = app.store.verifications_for_run(run_id)
            events = [
                str(e["text"])
                for e in app.store.events_for_run(run_id, limit=1000)
                if "gate binding" in str(e["text"])
            ]
            print(f"canary said: {events[:1]}")
            print(f"rows recorded: {[(r.scope, r.binding) for r in rows]}")

            assert events, "the canary did not run, so this proves nothing"
            assert "BOUND" in events[0]
            assert rows, "no verification rows to carry the proof"
            # The row must agree with the canary, not sit at the default.
            assert {r.binding for r in rows} == {BINDING_PROVED}
        finally:
            app.close()

    async def test_without_the_canary_the_row_claims_nothing(self, tmp_path: Path) -> None:
        """Unproved must stay unproved: silence is not evidence."""
        app = await make_project(tmp_path)
        app = _set_verify(app, ["true"])  # binding_check defaults to false
        try:
            run_id = await manual_run(
                app,
                [(spec("t", "FAKE:write:out.txt:done"), assign("alpha", "beta"))],
            )
            await app.orchestrator.execute(run_id)
            rows = app.store.verifications_for_run(run_id)
            assert rows
            assert {r.binding for r in rows} == {BINDING_NOT_CHECKED}
        finally:
            app.close()


class TestBindingProofIsPaidOnce:
    """On by default only works if the second run does not pay again."""

    async def _project(self, tmp_path: Path) -> App:
        app = await make_project(tmp_path)
        (app.root / "seed.py").write_text("VALUE = 1\n")
        (app.root / "check.py").write_text(
            "import ast, pathlib\n"
            "for path in pathlib.Path().glob('*.py'):\n"
            "    ast.parse(path.read_text())\n"
        )
        await GitRepo(app.root).add_all_and_commit("seed and checker")
        config_path = app.root / ".orkestra" / "config.toml"
        config_path.write_text(
            config_path.read_text() + f'\n[verify]\ncommands = ["{sys.executable} check.py"]\n'
        )
        app.close()
        return build_app(app.root, offline=True)

    async def test_the_check_defaults_on_and_proves_once(self, tmp_path: Path) -> None:
        app = await self._project(tmp_path)
        try:
            assert app.config.verify.binding_check is True, (
                "the differentiator must be on by default or the field never sees it"
            )
            calls: list[Path] = []
            import orkestra.verify as verify_pkg

            real = verify_pkg.prove_binding

            async def counting(worktree, commands, **kwargs):  # type: ignore[no-untyped-def]
                calls.append(worktree)
                return await real(worktree, commands, **kwargs)

            verify_pkg.prove_binding = counting  # type: ignore[assignment]
            try:
                for n in (1, 2):
                    run_id = await manual_run(
                        app,
                        [(spec(f"t{n}", f"FAKE:write:mod{n}.py:X = {n}"), assign("alpha", "beta"))],
                    )
                    await app.orchestrator.execute(run_id)
                    rows = app.store.verifications_for_run(run_id)
                    print(f"run {n}: {[(r.scope, r.binding) for r in rows]}")
                    assert rows and {r.binding for r in rows} == {BINDING_PROVED}
            finally:
                verify_pkg.prove_binding = real  # type: ignore[assignment]

            print(f"prove_binding executed {len(calls)} time(s) across two runs")
            assert len(calls) == 1, (
                "the second run re-proved a verdict that cannot have changed; "
                "the cache is the reason this can be on by default"
            )
        finally:
            app.close()

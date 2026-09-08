"""Guards on the verification record itself.

The value of a stored verdict is entirely in the fields around it, so
these tests defend the fields: the binding default (which must never
silently become an unearned claim), the environment fingerprint (which
is the only thing distinguishing two runs of the same argv on the same
tree), and the rule that only executed commands become records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.store import Store
from orkestra.store.db import Database
from orkestra.verify.record import (
    BINDING_NOT_CHECKED,
    BINDING_PROVED,
    SCOPE_TASK,
    VerificationRecord,
    env_fingerprint,
    output_digest,
    records_for_outcome,
    resolve_executable,
)
from orkestra.verify.runner import CommandResult, VerificationOutcome


def _outcome(*results: CommandResult) -> VerificationOutcome:
    return VerificationOutcome(results=list(results))


def _result(command: str, exit_code: int = 0, duration_s: float = 1.5) -> CommandResult:
    return CommandResult(
        command=command,
        exit_code=exit_code,
        duration_s=duration_s,
        stdout_tail="out",
        stderr_tail="",
    )


async def _records(outcome: VerificationOutcome, tmp_path: Path, **kwargs: object) -> list:
    defaults: dict = {
        "run_id": "run_1",
        "task_id": "task_1",
        "scope": SCOPE_TASK,
        "commit_sha": "c" * 40,
        "tree_sha": "t" * 40,
        "cwd": tmp_path,
        "env": {"PATH": "/usr/bin"},
    }
    defaults.update(kwargs)
    return await records_for_outcome(outcome, **defaults)


class TestBindingDefault:
    async def test_binding_defaults_to_not_checked(self, tmp_path: Path) -> None:
        # Nothing in this module measures binding, so anything other than
        # not_checked here would be an unearned claim.
        records = await _records(_outcome(_result("true")), tmp_path)
        assert [r.binding for r in records] == [BINDING_NOT_CHECKED]

    async def test_binding_is_a_caller_supplied_seam(self, tmp_path: Path) -> None:
        records = await _records(_outcome(_result("true")), tmp_path, binding=BINDING_PROVED)
        assert records[0].binding == BINDING_PROVED

    def test_unknown_scope_or_binding_is_refused(self) -> None:
        fields = {
            "run_id": "run_1",
            "task_id": None,
            "commit_sha": "c",
            "tree_sha": "t",
            "command": "true",
            "argv_json": '["true"]',
            "exe_realpath": "/bin/true",
            "exe_version": "",
            "env_fingerprint": "sha256:x",
            "exit_code": 0,
            "duration_s": 0.1,
            "output_digest": "sha256:y",
        }
        with pytest.raises(ValueError, match="scope"):
            VerificationRecord(scope="whatever", binding=BINDING_NOT_CHECKED, **fields)
        with pytest.raises(ValueError, match="binding"):
            VerificationRecord(scope=SCOPE_TASK, binding="green-ish", **fields)


class TestFingerprints:
    def test_env_fingerprint_changes_with_pythonpath(self) -> None:
        # PYTHONPATH is exactly what decides whether a Python gate reads the
        # worktree or somewhere else, so it must move the fingerprint.
        base = {"PATH": "/usr/bin"}
        assert env_fingerprint(base) != env_fingerprint({**base, "PYTHONPATH": "/w/src"})

    def test_env_fingerprint_is_order_independent(self) -> None:
        assert env_fingerprint({"A": "1", "B": "2"}) == env_fingerprint({"B": "2", "A": "1"})

    def test_output_digest_tracks_the_captured_tails(self) -> None:
        a = output_digest(_result("true"))
        b = output_digest(
            CommandResult(
                command="true", exit_code=0, duration_s=1.5, stdout_tail="other", stderr_tail=""
            )
        )
        assert a.startswith("sha256:")
        assert a != b


class TestExecutableResolution:
    def test_relative_path_resolves_against_the_worktree(self, tmp_path: Path) -> None:
        script = tmp_path / "gate.sh"
        script.write_text("#!/bin/sh\n")
        resolved = resolve_executable("./gate.sh", tmp_path, {"PATH": "/usr/bin"})
        assert Path(resolved) == script.resolve()

    def test_missing_executable_resolves_to_empty(self, tmp_path: Path) -> None:
        assert (
            resolve_executable("definitely-not-a-real-binary", tmp_path, {"PATH": "/usr/bin"}) == ""
        )


class TestStoreRoundTrip:
    async def test_rows_come_back_in_insertion_order_with_every_field(self, tmp_path: Path) -> None:
        store = Store(Database(tmp_path / "db.sqlite"))
        outcome = _outcome(_result("first", duration_s=2.25), _result("second", exit_code=7))
        records = await _records(outcome, tmp_path)
        ids = store.add_verifications(records)
        assert len(ids) == 2

        rows = store.verifications_for_run("run_1")
        assert [r.verification_id for r in rows] == ids
        assert [r.command for r in rows] == ["first", "second"]
        assert [r.exit_code for r in rows] == [0, 7]
        assert [r.duration_s for r in rows] == [2.25, 1.5]
        assert [r.passed for r in rows] == [True, False]
        assert [r.argv for r in rows] == [["first"], ["second"]]
        assert rows[0].tree_sha == "t" * 40
        assert rows[0].commit_sha == "c" * 40

        assert store.verifications_for_run("run_1", scope="accept") == []
        assert store.verifications_for_run("run_1", task_id="nope") == []
        assert store.verifications_for_run("other_run") == []

    def test_empty_record_list_writes_nothing(self, tmp_path: Path) -> None:
        store = Store(Database(tmp_path / "db.sqlite"))
        assert store.add_verifications([]) == []
        assert store.verifications_for_run("run_1") == []

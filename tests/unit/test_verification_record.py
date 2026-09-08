"""Guards on the verification record itself.

The value of a stored verdict is entirely in the fields around it, so
these tests defend the fields: the binding default (which must never
silently become an unearned claim), the environment fingerprint (which
is the only thing distinguishing two runs of the same argv on the same
tree), and the rule that only executed commands become records.
"""

from __future__ import annotations

import json
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
            "tree_clean": True,
            "dirty_digest": "",
            "attempt_id": None,
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


class TestColumnsMeanWhatTheySay:
    """Three columns previously described something other than what ran."""

    async def test_environment_is_captured_not_rebuilt(self, tmp_path: Path) -> None:
        """The fingerprint must describe the environment the gate really got.

        Rebuilding it afterwards agrees with reality only while nothing
        passes env_extra, and the gate binding work passes a worktree
        PYTHONPATH on every run.
        """
        from orkestra.verify.runner import gate_env, run_verification, subprocess_env

        outcome = await run_verification(
            ["true"], tmp_path, env_extra={"ORKESTRA_TEST_MARKER": "captured"}
        )
        # What actually ran, versus what a second reconstruction would guess.
        assert outcome.env.get("ORKESTRA_TEST_MARKER") == "captured"
        print("captured  :", env_fingerprint(outcome.env))
        print("rebuilt   :", env_fingerprint(subprocess_env()))
        print("gate_env  :", env_fingerprint(gate_env(tmp_path)))
        assert env_fingerprint(outcome.env) != env_fingerprint(subprocess_env())

        records = await records_for_outcome(
            outcome,
            run_id="r",
            task_id=None,
            scope=SCOPE_TASK,
            commit_sha="c",
            tree_sha="t",
            cwd=tmp_path,
            env=outcome.env,
        )
        assert records[0].env_fingerprint == env_fingerprint(outcome.env)

    async def test_a_repo_local_binary_is_never_probed(self, tmp_path: Path) -> None:
        """A gate binary living in the tree is the code under test."""
        from orkestra.verify.record import probe_version

        fake = tmp_path / "pytest"
        witness = tmp_path / "probe-ran"
        fake.write_text(f"#!/bin/sh\ntouch {witness}\necho 'pytest 1.0'\n")
        fake.chmod(0o755)

        version = await probe_version(str(fake), "pytest", tmp_path, {"PATH": "/usr/bin"})
        assert version == ""
        assert not witness.exists(), "a binary inside the worktree was executed"

    async def test_argv_survives_redaction_and_truncation(self, tmp_path: Path) -> None:
        """A stored argv must still parse as JSON, or it is simply lost."""
        from orkestra.store.repo import _argv_json

        stored = _argv_json('["pytest", "--token=sk-not-a-real-secret-value-here"]')
        parsed = json.loads(stored)
        assert parsed[0] == "pytest"

        long_argv = json.dumps(["pytest", *[f"--flag-{i}={'x' * 200}" for i in range(60)]])
        trimmed = json.loads(_argv_json(long_argv))
        assert trimmed[0] == "pytest"
        assert len(_argv_json(long_argv)) <= 4000


class TestTreeShaHonesty:
    """`tree_sha` names HEAD's tree, which is not always what the gate read."""

    async def test_dirty_worktree_is_recorded_as_such(self, tmp_path: Path) -> None:
        from orkestra.verify.record import dirty_state
        from orkestra.workspace.git import GitRepo

        root = tmp_path / "proj"
        root.mkdir()
        repo = GitRepo(root)
        await repo.init()
        (root / "a.py").write_text("VALUE = 1\n")
        await repo.add_all_and_commit("initial")

        clean, digest = await dirty_state(repo)
        assert clean is True
        assert digest == ""

        # Verification runs on every task; only a mutating task commits
        # first. So this is the ordinary case for research and review work.
        (root / "a.py").write_text("VALUE = 2\n")
        dirty, dirty_digest = await dirty_state(repo)
        print("clean:", clean, "| dirty:", dirty, "| digest:", dirty_digest[:24])
        assert dirty is False
        assert dirty_digest != ""

        records = await records_for_outcome(
            _outcome(_result("true")),
            run_id="r",
            task_id=None,
            scope=SCOPE_TASK,
            commit_sha=await repo.rev_parse("HEAD"),
            tree_sha=await repo.rev_parse("HEAD^{tree}"),
            tree_clean=dirty,
            dirty_digest=dirty_digest,
            cwd=root,
            env={"PATH": "/usr/bin"},
        )
        # The row still carries a tree sha, but no longer claims it is what ran.
        assert records[0].tree_clean is False
        assert records[0].dirty_digest == dirty_digest

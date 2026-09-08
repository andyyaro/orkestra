"""The binding canary, against a real reproduction of the unbound gate.

This module mechanically reproduces the failure that motivated
``orkestra.verify.binding``: a src-layout Python project whose interpreter
carries an absolute path to *another* checkout on ``sys.path`` (what an
editable install's ``.pth`` file does), so the gate run inside a worktree
tests the other checkout and cannot fail no matter what the worktree
contains.

Nothing here is mocked. A real git repository is created, a real worktree
is added, a real source file is sabotaged, and a real pytest subprocess is
the gate.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from orkestra.schemas.config import VerifyConfig
from orkestra.verify.binding import BindingStatus, _module_name, prove_binding
from orkestra.verify.runner import gate_env, run_verification, worktree_pythonpath

SABOTAGE = 'raise RuntimeError("SABOTAGED")\n'


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@dataclass
class Repro:
    """A main checkout, a worktree of it, and the gate that lies."""

    main: Path
    worktree: Path
    gate: list[str]
    poison: dict[str, str]

    @property
    def package_init(self) -> Path:
        return self.worktree / "src" / "widget" / "__init__.py"


@pytest.fixture
def repro(tmp_path: Path) -> Repro:
    main = tmp_path / "main"
    (main / "src" / "widget").mkdir(parents=True)
    (main / "tests").mkdir()
    (main / "src" / "widget" / "__init__.py").write_text("VALUE = 41\n")
    (main / "src" / "widget" / "core.py").write_text(
        "from widget import VALUE\n\n\ndef bump() -> int:\n    return VALUE + 1\n"
    )
    (main / "tests" / "test_core.py").write_text(
        "from widget.core import bump\n\n\ndef test_bump() -> None:\n    assert bump() == 42\n"
    )
    _git("init", "-q", "-b", "main", cwd=main)
    _git("add", "-A", cwd=main)
    _git("commit", "-q", "-m", "initial", cwd=main)
    worktree = tmp_path / "wt"
    _git("worktree", "add", "--detach", "-q", str(worktree), "HEAD", cwd=main)
    # The exact command docs/CONFIGURATION.md and every shipped example
    # prescribe, run the way Orkestra runs it: cwd = the worktree.
    gate = [f"{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider tests"]
    # What an editable install of the *main* checkout does to every process
    # using that interpreter: an absolute path, independent of cwd.
    return Repro(main=main, worktree=worktree, gate=gate, poison={"PYTHONPATH": str(main / "src")})


class TestTheGateReallyIsUnbound:
    """First: prove the disease exists, in this test's own fixture."""

    async def test_sabotaged_worktree_still_passes_without_the_mitigation(
        self, repro: Repro
    ) -> None:
        repro.package_init.write_text(SABOTAGE)
        outcome = await run_verification(
            repro.gate, repro.worktree, timeout_s=300, env_extra=repro.poison
        )
        print("unmitigated gate exit:", outcome.results[-1].exit_code)
        print("unmitigated gate tail:", outcome.results[-1].stdout_tail[-300:])
        assert outcome.passed, "fixture no longer reproduces the unbound gate"

    async def test_worktree_pythonpath_catches_the_same_sabotage(self, repro: Repro) -> None:
        repro.package_init.write_text(SABOTAGE)
        outcome = await run_verification(repro.gate, repro.worktree, timeout_s=300)
        print("mitigated gate exit:", outcome.results[-1].exit_code)
        assert not outcome.passed
        assert "SABOTAGED" in outcome.failure_detail()


class TestBindingCanary:
    """Then: prove the canary reports it, both ways round."""

    async def test_unmitigated_environment_is_reported_unbound(self, repro: Repro) -> None:
        original = repro.package_init.read_bytes()
        proof = await prove_binding(
            repro.worktree, repro.gate, timeout_s=300, env_extra=repro.poison
        )
        print("proof:", proof.headline)
        print("detail:", proof.detail)
        assert proof.status is BindingStatus.UNBOUND
        assert proof.bound is False
        assert proof.resolved_source is not None
        assert proof.resolved_source.startswith(str(repro.main.resolve()))
        # The canary corrupts files; it must leave none behind.
        assert repro.package_init.read_bytes() == original

    async def test_worktree_pythonpath_is_reported_bound(self, repro: Repro) -> None:
        original = repro.package_init.read_bytes()
        proof = await prove_binding(repro.worktree, repro.gate, timeout_s=300)
        print("proof:", proof.headline)
        print("detail:", proof.detail)
        assert proof.status is BindingStatus.BOUND
        assert proof.bound is True
        assert proof.baseline_exit == 0
        assert proof.corrupted_exit not in (None, 0)
        assert proof.corrupted_path is not None
        assert proof.resolved_source is not None
        assert proof.resolved_source.startswith(str(repro.worktree.resolve()))
        assert repro.package_init.read_bytes() == original

    async def test_inherited_poison_does_not_beat_the_worktree(
        self, repro: Repro, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The .pth path is present in the ambient environment too, exactly
        # as it is for a real editable install. Ours must still win.
        monkeypatch.setenv("PYTHONPATH", str(repro.main / "src"))
        proof = await prove_binding(repro.worktree, repro.gate, timeout_s=300)
        print("proof:", proof.headline)
        assert proof.bound is True

    async def test_vacuous_gate_is_unbound_not_passing(self, repro: Repro) -> None:
        # A gate that cannot fail for any code reason: exit 0 on every tree.
        proof = await prove_binding(
            repro.worktree, [f"{shlex.quote(sys.executable)} -c pass"], timeout_s=300
        )
        print("proof:", proof.headline)
        assert proof.status is BindingStatus.UNBOUND
        assert proof.baseline_exit == 0
        assert proof.corrupted_exit == 0

    async def test_already_failing_gate_is_cannot_check(self, repro: Repro) -> None:
        proof = await prove_binding(
            repro.worktree,
            [f"{shlex.quote(sys.executable)} -c {shlex.quote('raise SystemExit(3)')}"],
            timeout_s=300,
        )
        print("proof:", proof.headline)
        assert proof.status is BindingStatus.CANNOT_CHECK
        assert proof.bound is False
        assert proof.baseline_exit == 3

    async def test_no_commands_is_cannot_check(self, repro: Repro) -> None:
        proof = await prove_binding(repro.worktree, [], timeout_s=300)
        assert proof.status is BindingStatus.CANNOT_CHECK
        assert "no verification commands" in proof.reason

    async def test_prefers_a_file_the_diff_touched(self, repro: Repro) -> None:
        proof = await prove_binding(
            repro.worktree,
            repro.gate,
            changed_paths=["src/widget/core.py"],
            timeout_s=300,
        )
        assert proof.bound is True
        assert proof.corrupted_path == "src/widget/core.py"


class TestWorktreePythonPath:
    def test_src_layout_names_src_and_not_the_root(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        value = worktree_pythonpath(tmp_path, "/somewhere/else/src")
        entries = value.split(os.pathsep)
        assert entries[0] == str((tmp_path / "src").resolve())
        # The root must NOT be here: it holds the project's top-level modules,
        # and a project owning a types.py would shadow the standard library.
        assert str(tmp_path.resolve()) not in entries
        assert value.endswith("/somewhere/else/src")

    def test_flat_layout_names_the_root_and_no_duplicates(self, tmp_path: Path) -> None:
        value = worktree_pythonpath(tmp_path, f"{tmp_path.resolve()}:")
        assert value == str(tmp_path.resolve())

    def test_a_project_owning_types_py_does_not_break_the_interpreter(self, tmp_path: Path) -> None:
        """The shadowing this function must never cause, stated as behaviour."""
        (tmp_path / "src").mkdir()
        (tmp_path / "types.py").write_text("raise RuntimeError('stdlib shadowed')\n")
        env = dict(os.environ)
        env["PYTHONPATH"] = worktree_pythonpath(tmp_path)
        result = subprocess.run(
            [sys.executable, "-c", "import types; print(types.__name__)"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "types"


class TestModuleName:
    """A src layout must not drag its `src` prefix into the dotted name."""

    def test_package_init(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "widget"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        assert _module_name("src/widget/__init__.py", tmp_path) == "widget"

    def test_nested_module_under_src(self, tmp_path: Path) -> None:
        sub = tmp_path / "src" / "widget" / "verify"
        sub.mkdir(parents=True)
        (tmp_path / "src" / "widget" / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("")
        (sub / "core.py").write_text("")
        assert _module_name("src/widget/verify/core.py", tmp_path) == "widget.verify.core"

    def test_top_level_script_is_its_own_module(self, tmp_path: Path) -> None:
        (tmp_path / "tool.py").write_text("")
        assert _module_name("tool.py", tmp_path) == "tool"


class TestDefaults:
    """The fix is on by default; the audit that costs two gate runs is not."""

    def test_the_mitigation_is_always_on(self, tmp_path: Path) -> None:
        # gate_env is what actually binds the common Python case, and nothing
        # gates it behind a setting.
        (tmp_path / "src").mkdir()
        env = gate_env(tmp_path)
        assert env["PYTHONPATH"].startswith(str((tmp_path / "src").resolve()))

    def test_the_audit_is_on_because_it_is_now_cheap(self) -> None:
        # It was off while it cost two extra gate runs per run. Cached on the
        # gate and the environment it is paid once per configuration, which is
        # what makes it affordable to be the default - and the default is the
        # only reason the evidence field is ever anything but not_checked.
        assert VerifyConfig().binding_check is True

"""A binding proof is reusable, and the cache key says exactly when.

The proof costs two extra gate runs, which is why it shipped off by default
and therefore never ran in the field: the one metric that measures the
project's differentiator read `not_checked` for everybody. It is affordable
if it is asked once per configuration rather than once per run, and it is
answerable that way because the verdict depends on the gate and the
environment, not on the tree. That was measured: identical across three
different trees of this repository, and it flipped only when the environment
changed.
"""

from __future__ import annotations

import os
from pathlib import Path

from orkestra.verify.binding import BindingStatus, binding_cache_key
from orkestra.verify.runner import gate_env


def _layout(root: Path) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    return root


class TestBindingCacheKey:
    def test_two_worktrees_ask_the_same_question(self, tmp_path: Path) -> None:
        """Otherwise every key holds an absolute path and nothing ever hits."""
        a, b = _layout(tmp_path / "a"), _layout(tmp_path / "b")
        commands = ["pytest -q"]
        assert binding_cache_key(commands, a, gate_env(a)) == binding_cache_key(
            commands, b, gate_env(b)
        )

    def test_a_different_environment_is_a_different_question(self, tmp_path: Path) -> None:
        root = _layout(tmp_path / "a")
        commands = ["pytest -q"]
        here = binding_cache_key(commands, root, gate_env(root))
        elsewhere = binding_cache_key(
            commands, root, gate_env(root, {"PYTHONPATH": "/some/other/checkout/src"})
        )
        assert here != elsewhere, "an inherited path change must invalidate the proof"

    def test_a_different_gate_is_a_different_question(self, tmp_path: Path) -> None:
        root = _layout(tmp_path / "a")
        assert binding_cache_key(["pytest -q"], root, gate_env(root)) != binding_cache_key(
            ["pytest -q", "ruff check ."], root, gate_env(root)
        )

    def test_the_worktree_is_normalised_out_but_the_rest_is_not(self, tmp_path: Path) -> None:
        """Only entries inside the worktree are dropped; the rest still count."""
        root = _layout(tmp_path / "a")
        env = gate_env(root)
        assert str((root / "src").resolve()) in env["PYTHONPATH"].split(os.pathsep)
        # Same env plus an outside entry must change the key.
        outside = dict(env)
        outside["PYTHONPATH"] = env["PYTHONPATH"] + os.pathsep + "/opt/other"
        assert binding_cache_key(["x"], root, env) != binding_cache_key(["x"], root, outside)


class TestProbeSurvivesNoisyImports:
    """A module that prints on import must not read as UNBOUND.

    Importing a module runs it, and plenty of real modules print on import:
    logging setup, banners, deprecation notices. Reading the probe's whole
    stdout as a path mistakes that output for the answer, the containment
    check fails against something that was never a path, and a correct gate
    is declared unbound. That blocks the run, which is the failure mode that
    gets a checker switched off for good.
    """

    async def test_a_printing_module_still_resolves(self, tmp_path: Path) -> None:
        import subprocess
        import sys

        from orkestra.verify.binding import prove_binding

        root = tmp_path / "proj"
        (root / "src").mkdir(parents=True)
        (root / "src" / "noisy.py").write_text("print('configuring logging...')\nVALUE = 1\n")
        (root / "check.py").write_text("import noisy\nassert noisy.VALUE == 1\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "base"],
            cwd=root,
            check=True,
        )

        proof = await prove_binding(root, [f"{sys.executable} check.py"])
        print(f"verdict: {proof.status.value} | {proof.reason[:120]}")
        assert proof.status is not BindingStatus.UNBOUND, (
            "a module printing on import was mistaken for a resolved path"
        )

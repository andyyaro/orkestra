"""Prove that a verification gate actually reads the worktree it is aimed at.

Orkestra runs the user's ``[verify]`` commands with ``cwd`` set to a task
worktree and then treats exit 0 as a statement *about that worktree*. That
inference is not free, and on the most common modern Python layout it is
false. A src-layout project installed editable writes a ``.pth`` file
holding an absolute path to the main checkout:

    $ cat .venv/lib/python3.12/site-packages/_editable_impl_myproj.pth
    /home/me/myproj/src

That path is on ``sys.path`` for every process using that interpreter,
whatever its ``cwd``. So ``pytest -q`` run inside a worktree imports, and
tests, the code in the *main checkout*: sabotage the worktree and the gate
still exits 0. The failure is silent and always false-clean, which is the
worst possible shape for a verification system.

This module answers one question deterministically - no LLM, no network:
*does this gate, run here, actually read this tree?* It answers BOUND,
UNBOUND, or CANNOT-CHECK. CANNOT-CHECK is not a pass; it means the
question could not be settled and the caller must say so out loud.

Method:

1. Resolve the import (Python only, and only ever *against* the gate): ask
   the gate's own interpreter where the package comes from. A path outside
   the worktree proves UNBOUND on its own, cheaply, before any test runs.
   The reverse is not proof - ``python -c`` prepends the cwd to
   ``sys.path`` while a console script does not - so a path inside the
   worktree only lets the check continue.
2. Run the gate on the clean tree and record the exit code.
3. Corrupt one tracked, non-test source file with a line that is
   syntactically fatal in every C-family and Python-family language, run
   the gate again, and require the exit code to change. Restore the file
   always, including on exception.

A gate that does not react to a deliberately broken source file is either
reading another tree or not reading any source at all (the vacuous
``test -f README.md`` gate). Both are reported the same way, because both
mean the same thing: this exit code is not evidence.
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from orkestra.verify.runner import gate_env, run_verification

#: Extensions we are willing to corrupt. Data and markup are excluded: a
#: broken JSON file proves nothing about whether the gate read the code.
_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".swift",
        ".php",
        ".scala",
    }
)

_SKIP_DIRS = frozenset(
    {
        "test",
        "tests",
        "testing",
        "__tests__",
        "spec",
        "specs",
        "fixtures",
        "testdata",
        "examples",
        "example",
        "vendor",
        "node_modules",
        "third_party",
        "migrations",
        "build",
        "dist",
    }
)

#: Unbalanced parentheses: a parse error in Python, JavaScript, TypeScript,
#: Go, Rust, Java, C and friends alike, so one corruption serves every
#: language we are willing to touch. It is also unmistakable in output.
CANARY_LINE = "((( orkestra binding canary - deliberately corrupted, restored automatically\n"

_PROBE_TIMEOUT_S = 120.0
_MAX_CANDIDATES = 2


class BindingStatus(StrEnum):
    """Three outcomes, and CANNOT-CHECK is never a pass."""

    BOUND = "bound"
    UNBOUND = "unbound"
    CANNOT_CHECK = "cannot_check"


@dataclass(frozen=True)
class BindingProof:
    """What was tried, what happened, and therefore what may be claimed."""

    status: BindingStatus
    reason: str
    commands: tuple[str, ...] = ()
    corrupted_path: str | None = None
    corruption: str | None = None
    baseline_exit: int | None = None
    corrupted_exit: int | None = None
    resolved_source: str | None = None

    @property
    def bound(self) -> bool:
        return self.status is BindingStatus.BOUND

    @property
    def label(self) -> str:
        if self.status is BindingStatus.BOUND:
            return "BOUND"
        return "UNBOUND" if self.status is BindingStatus.UNBOUND else "CANNOT-CHECK"

    @property
    def headline(self) -> str:
        return f"{self.label}: {self.reason}"

    @property
    def detail(self) -> str:
        """Every measured number, printed whether or not it was decisive."""
        parts: list[str] = []
        if self.commands:
            parts.append("gate: " + " && ".join(self.commands))
        if self.corrupted_path:
            parts.append(f"corrupted: {self.corrupted_path}")
        if self.baseline_exit is not None:
            parts.append(f"clean exit: {self.baseline_exit}")
        if self.corrupted_exit is not None:
            parts.append(f"corrupted exit: {self.corrupted_exit}")
        if self.resolved_source:
            parts.append(f"imports resolve to: {self.resolved_source}")
        return "; ".join(parts)

    @classmethod
    def cannot_check(
        cls,
        reason: str,
        *,
        commands: tuple[str, ...] = (),
        corrupted_path: str | None = None,
        corruption: str | None = None,
        baseline_exit: int | None = None,
        corrupted_exit: int | None = None,
        resolved_source: str | None = None,
    ) -> BindingProof:
        """The question could not be settled. This is not a pass."""
        return cls(
            status=BindingStatus.CANNOT_CHECK,
            reason=reason,
            commands=commands,
            corrupted_path=corrupted_path,
            corruption=corruption,
            baseline_exit=baseline_exit,
            corrupted_exit=corrupted_exit,
            resolved_source=resolved_source,
        )


# --------------------------------------------------------------- helpers


async def _capture(argv: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    """Run argv without a shell; return (exit code, stdout)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except OSError:
        return -1, ""
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT_S)
    except TimeoutError:  # pragma: no cover - probe is a few milliseconds
        proc.kill()
        await proc.wait()
        return -1, ""
    return proc.returncode if proc.returncode is not None else -1, stdout.decode(errors="replace")


def _looks_like_test(rel: str) -> bool:
    path = PurePosixPath(rel)
    if any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts[:-1]):
        return True
    stem = path.name.split(".")[0]
    return (
        stem in {"conftest", "setup"}
        or stem.startswith("test_")
        or stem.endswith(("_test", "_spec"))
        or ".test." in path.name
        or ".spec." in path.name
    )


async def _tracked_sources(worktree: Path, env: dict[str, str]) -> list[str]:
    """Tracked, non-test source files, repo-relative, in git's order."""
    code, out = await _capture(["git", "ls-files", "-z"], worktree, env)
    if code != 0:
        return []
    return [
        rel
        for rel in out.split("\0")
        if rel
        and PurePosixPath(rel).suffix in _SOURCE_SUFFIXES
        and not _looks_like_test(rel)
        and (worktree / rel).is_file()
    ]


def _rank(rel: str, touched: frozenset[str]) -> tuple[int, int, int, str]:
    path = PurePosixPath(rel)
    return (
        0 if rel in touched else 1,
        0 if path.name == "__init__.py" else 1,
        len(path.parts),
        rel,
    )


def _candidates(sources: Sequence[str], touched: Sequence[str]) -> list[str]:
    """Best file to corrupt first, plus one structurally different backup.

    Preference order is: a file the task's own diff touched (the gate is
    most likely to exercise it), then a package initialiser (every import
    of the package executes it, so a syntax error there cannot be missed),
    then the shallowest path. The second pick exists because a first pick
    that nothing imports would report a bound gate as unbound.
    """
    touched_set = frozenset(touched)
    ordered = sorted(sources, key=lambda rel: _rank(rel, touched_set))
    if not ordered:
        return []
    picks = [ordered[0]]
    for rel in ordered:
        if len(picks) >= _MAX_CANDIDATES:
            break
        if rel not in picks and PurePosixPath(rel).name == "__init__.py":
            picks.append(rel)
    for rel in ordered:
        if len(picks) >= _MAX_CANDIDATES:
            break
        if rel not in picks:
            picks.append(rel)
    return picks


def _module_name(rel: str, worktree: Path) -> str | None:
    """Dotted import name for a .py file, walking up while __init__.py exists."""
    path = PurePosixPath(rel)
    if path.suffix != ".py":
        return None
    parts = list(path.parts)
    parts[-1] = path.name[: -len(".py")]
    if parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return None
    # Trim leading directories that are not packages (src/, lib/, …).
    while len(parts) > 1:
        package_root = worktree.joinpath(*parts[:-1]) / "__init__.py"
        if package_root.exists():
            break
        parts.pop(0)
    return ".".join(parts)


def _python_argv(commands: Sequence[str]) -> list[str] | None:
    """The interpreter the gate itself would use, as argv wanting ``-c``.

    A console script such as ``pytest`` has a shebang pointing at its own
    interpreter, so the ``python`` next to it on disk is the right one -
    which matters, because that is exactly the interpreter whose ``.pth``
    files decide the question.
    """
    for command in commands:
        try:
            argv = shlex.split(command)
        except ValueError:  # pragma: no cover - caught earlier by the gate check
            continue
        if not argv:
            continue
        exe = PurePosixPath(argv[0]).name
        if exe.startswith("python"):
            return [argv[0], "-c"]
        if exe == "uv" and argv[1:2] == ["run"]:
            # `uv run` re-resolves the environment for the current directory,
            # which is the mitigation as well as the probe.
            return [argv[0], "run", "python", "-c"]
        resolved = shutil.which(argv[0])
        if resolved:
            sibling = Path(resolved).parent / "python"
            if sibling.exists():
                return [str(sibling), "-c"]
    fallback = shutil.which("python3") or shutil.which("python")
    return [fallback, "-c"] if fallback else None


def _probe_code(module: str) -> str:
    return (
        "import importlib, os, sys\n"
        f"m = importlib.import_module({module!r})\n"
        "p = getattr(m, '__file__', None)\n"
        "if not p:\n"
        "    found = list(getattr(m, '__path__', []) or [])\n"
        "    p = found[0] if found else ''\n"
        "sys.stdout.write(os.path.realpath(p) if p else '')\n"
    )


async def resolve_python_source(
    worktree: Path,
    commands: Sequence[str],
    module: str,
    env: dict[str, str],
) -> str | None:
    """Where the gate's interpreter actually imports ``module`` from."""
    argv = _python_argv(commands)
    if argv is None:  # pragma: no cover - a machine with no python at all
        return None
    code, out = await _capture([*argv, _probe_code(module)], worktree, env)
    resolved = out.strip()
    return resolved if code == 0 and resolved else None


def _is_inside(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
    except ValueError:
        return False
    return True


# ----------------------------------------------------------------- proof


async def prove_binding(
    worktree: Path,
    commands: Sequence[str],
    *,
    changed_paths: Sequence[str] = (),
    timeout_s: int = 900,
    env_extra: dict[str, str] | None = None,
) -> BindingProof:
    """Prove (or refuse to claim) that this gate reads this worktree.

    ``env_extra`` is passed through to the gate exactly as the kernel
    passes it, so the proof describes the environment the gate really
    runs in, not an idealised one.
    """
    gate = [c for c in commands if c.strip()]
    root = Path(worktree).resolve()
    if not gate:
        return BindingProof.cannot_check(
            "no verification commands are configured, so there is no gate to bind"
        )
    if not root.is_dir():
        return BindingProof.cannot_check(f"{root} is not a directory", commands=tuple(gate))

    env = gate_env(root, env_extra)
    sources = await _tracked_sources(root, env)
    if not sources:
        return BindingProof.cannot_check(
            "found no tracked, non-test source file in this tree to corrupt",
            commands=tuple(gate),
        )
    picks = _candidates(sources, changed_paths)

    # 1. Import resolution: cheap, and decisive when it fails.
    resolved: str | None = None
    for rel in picks:
        module = _module_name(rel, root)
        if module is None:
            continue
        resolved = await resolve_python_source(root, gate, module, env)
        if resolved is None:
            continue
        if not _is_inside(resolved, root):
            return BindingProof(
                status=BindingStatus.UNBOUND,
                reason=(
                    f"the gate's interpreter imports {module!r} from {resolved}, "
                    f"which is outside this worktree ({root}); the gate is testing "
                    "another checkout, so its exit code says nothing about this tree"
                ),
                commands=tuple(gate),
                resolved_source=resolved,
            )
        break

    # 2. Baseline.
    baseline = await run_verification(gate, root, timeout_s=timeout_s, env_extra=env_extra)
    if not baseline.results:  # pragma: no cover - gate is non-empty here
        return BindingProof.cannot_check(
            "the gate produced no result to compare against",
            commands=tuple(gate),
            resolved_source=resolved,
        )
    baseline_exit = baseline.results[-1].exit_code

    # 3. Corruption: the gate must notice.
    last_exit: int | None = None
    last_rel: str | None = None
    for rel in picks:
        last_rel = rel
        with _corrupted(root / rel):
            corrupted = await run_verification(gate, root, timeout_s=timeout_s, env_extra=env_extra)
        last_exit = corrupted.results[-1].exit_code if corrupted.results else None
        if last_exit is not None and last_exit != baseline_exit:
            return BindingProof(
                status=BindingStatus.BOUND,
                reason=(
                    f"corrupting {rel} in this worktree changed the gate's exit code "
                    f"from {baseline_exit} to {last_exit}, so the gate reads this tree"
                ),
                commands=tuple(gate),
                corrupted_path=rel,
                corruption=CANARY_LINE.strip(),
                baseline_exit=baseline_exit,
                corrupted_exit=last_exit,
                resolved_source=resolved,
            )

    if baseline_exit != 0:
        return BindingProof.cannot_check(
            f"the gate already fails on the unmodified tree (exit {baseline_exit}), "
            "so corrupting a file cannot change its verdict and binding cannot be "
            "decided; fix the gate, then check binding again",
            commands=tuple(gate),
            corrupted_path=last_rel,
            corruption=CANARY_LINE.strip(),
            baseline_exit=baseline_exit,
            corrupted_exit=last_exit,
            resolved_source=resolved,
        )
    return BindingProof(
        status=BindingStatus.UNBOUND,
        reason=(
            f"the gate returned exit {baseline_exit} both on this worktree and with "
            f"{last_rel} deliberately corrupted, so it is not reading this tree "
            "(or is not reading any source at all)"
        ),
        commands=tuple(gate),
        corrupted_path=last_rel,
        corruption=CANARY_LINE.strip(),
        baseline_exit=baseline_exit,
        corrupted_exit=last_exit,
        resolved_source=resolved,
    )


@contextlib.contextmanager
def _corrupted(path: Path) -> Iterator[None]:
    """Corrupt ``path`` for the body, and restore it whatever happens.

    The original bytes are held in memory *and* copied aside on disk, so a
    crash between the two writes still leaves a recoverable copy next to
    the temp file named in the traceback.
    """
    original = path.read_bytes()
    backup_dir = Path(tempfile.mkdtemp(prefix="orkestra-binding-"))
    backup = backup_dir / path.name
    shutil.copy2(path, backup)
    try:
        path.write_text(CANARY_LINE, encoding="utf-8")
        yield
    finally:
        path.write_bytes(original)
        if path.read_bytes() != original:  # pragma: no cover - filesystem failure
            msg = f"failed to restore {path}; the original is at {backup}"
            raise OSError(msg)
        shutil.rmtree(backup_dir, ignore_errors=True)

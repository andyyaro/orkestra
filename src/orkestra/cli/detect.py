"""Project-culture detection and spec-quality nudges for friendlier setup.

Heuristics only — everything here produces *suggestions* the user can
edit, never silent behavior changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def detect_verify_commands(root: Path) -> list[str]:
    """Guess deterministic acceptance commands from the repo's test culture."""
    commands: list[str] = []

    def has(*names: str) -> bool:
        return any((root / n).exists() for n in names)

    python_markers = has("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    tests_dir = has("tests", "test")
    if python_markers or tests_dir:
        pyproject = root / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
        if "pytest" in text or has("pytest.ini") or tests_dir:
            if (root / "uv.lock").exists():
                commands.append("uv run pytest -q")
            else:
                commands.append("pytest -q")

    package_json = root / "package.json"
    if package_json.exists():
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        if "test" in scripts and "no test specified" not in str(scripts["test"]):
            commands.append("npm test --silent")

    if has("Cargo.toml"):
        commands.append("cargo test")
    if has("go.mod"):
        commands.append("go test ./...")

    return commands


_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_ACCEPTANCE_HINTS = re.compile(
    r"(?i)\b(accept|must|should|verif|test|pass|criteri|exactly|require)"
)
_TEMPLATE_FILLER = re.compile(r"^\s*-\s*\.\.\.\s*$", re.MULTILINE)


def spec_nudges(spec_text: str) -> list[str]:
    """Friendly, non-blocking warnings about spec quality.

    Plan quality tracks spec quality almost 1:1 (observed in live runs) —
    these catch the most common weak-spec patterns before quota is spent.
    """
    nudges: list[str] = []
    stripped = spec_text.strip()
    if len(stripped) < 200:
        nudges.append(
            "your SPEC.md is very short — the director can only plan what "
            "you describe. A few concrete sentences per goal go a long way."
        )
    if _TEMPLATE_FILLER.search(spec_text):
        nudges.append(
            "SPEC.md still contains template placeholders ('- ...') — "
            "replace them with your actual goals and constraints."
        )
    if not _HEADING_RE.search(spec_text):
        nudges.append(
            "SPEC.md has no headings — structure (Goals / Constraints / "
            "Acceptance) helps the director decompose work."
        )
    if not _ACCEPTANCE_HINTS.search(spec_text):
        nudges.append(
            "SPEC.md doesn't state how success is judged — add acceptance "
            "criteria (testable statements) so reviews have a yardstick."
        )
    if "do not" not in spec_text.lower() and "don't" not in spec_text.lower():
        nudges.append(
            "consider stating what agents must NOT touch (directories, "
            "interfaces, dependencies) — boundaries prevent surprises."
        )
    return nudges

"""Model discovery per adapter, version-cached, with provenance.

Discovery never relies solely on hard-coded names: where a CLI exposes a
real listing surface (Antigravity's ``agy models``) it is queried live
and cached by adapter version; elsewhere we present *documented*
defaults clearly labeled as such, and manual entry is always available.

Provenance vocabulary: ``discovered`` (from the CLI), ``documented``
(from the vendor's docs, may age), ``manual`` (user-entered),
``default`` (adapter's own choice, no override).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from orkestra.adapters.base import AgentAdapter
from orkestra.adapters.runner import run_capture

CACHE_TTL_S = 7 * 24 * 3600  # refresh weekly, or when the version changes


@dataclass(frozen=True)
class ModelCatalog:
    """What a user can choose for one adapter."""

    adapter_id: str
    models: list[str] = field(default_factory=list)
    provenance: str = "documented"  # discovered | documented | none
    note: str = ""
    efforts: list[str] = field(default_factory=list)


#: Documented model aliases (labeled as such in every UI; sources: each
#: vendor's CLI docs as of 2026-07). Live discovery supersedes these
#: whenever the CLI offers a listing surface.
_DOCUMENTED: dict[str, ModelCatalog] = {
    "claude-code": ModelCatalog(
        adapter_id="claude-code",
        models=["fable", "opus", "sonnet", "haiku"],
        provenance="documented",
        note="aliases resolve to the newest model of each tier; any full model name works too",
    ),
    "codex-cli": ModelCatalog(
        adapter_id="codex-cli",
        models=[],
        provenance="none",
        note=(
            "Codex has no listing surface - any model id your ChatGPT plan "
            "supports (see /model inside codex)"
        ),
        efforts=["low", "medium", "high"],
    ),
    "gemini-cli": ModelCatalog(
        adapter_id="gemini-cli",
        models=["auto", "pro", "flash", "flash-lite"],
        provenance="documented",
        note="aliases from the Gemini CLI reference",
    ),
    "fake": ModelCatalog(
        adapter_id="fake",
        models=[],
        provenance="none",
        note="the fake adapter ignores models",
    ),
    "external": ModelCatalog(
        adapter_id="external",
        models=[],
        provenance="none",
        note="model choice is up to your external agent",
    ),
}


def _cache_path(root: Path) -> Path:
    return root / ".orkestra" / "cache" / "models.json"


def _read_cache(root: Path) -> dict[str, dict[str, object]]:
    path = _cache_path(root)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_cache(root: Path, cache: dict[str, dict[str, object]]) -> None:
    path = _cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=1), encoding="utf-8")


async def discover_models(
    adapter: AgentAdapter, project_root: Path, *, refresh: bool = False
) -> ModelCatalog:
    """Best available catalog for *adapter*, using the version-keyed cache."""
    adapter_id = adapter.adapter_id
    if adapter_id == "antigravity-cli":
        info = await adapter.detect()
        cache_key = f"{adapter_id}:{info.version}"
        cache = _read_cache(project_root)
        entry = cache.get(cache_key)
        cached_models = entry.get("models") if entry else None
        cached_ts = entry.get("ts", 0) if entry else 0
        if (
            not refresh
            and isinstance(cached_models, list)
            and isinstance(cached_ts, int | float)
            and time.time() - cached_ts < CACHE_TTL_S
        ):
            return ModelCatalog(
                adapter_id=adapter_id,
                models=[str(m) for m in cached_models],
                provenance="discovered",
                note=f"listed live by agy {info.version} (cached)",
                efforts=["low", "medium", "high"],
            )
        executable = adapter.which()
        if info.available and executable:
            code, out, _ = await run_capture([executable, "models"], timeout_s=30)
            models = [line.strip() for line in out.splitlines() if line.strip()]
            if code == 0 and models:
                cache[cache_key] = {"models": models, "ts": time.time()}
                _write_cache(project_root, cache)
                return ModelCatalog(
                    adapter_id=adapter_id,
                    models=models,
                    provenance="discovered",
                    note=f"listed live by agy {info.version}",
                    efforts=["low", "medium", "high"],
                )
        return ModelCatalog(
            adapter_id=adapter_id,
            models=[],
            provenance="none",
            note=(
                "agy is not signed in - models can be listed after `agy` "
                "login; manual entry works now"
            ),
            efforts=["low", "medium", "high"],
        )
    return _DOCUMENTED.get(
        adapter_id,
        ModelCatalog(
            adapter_id=adapter_id,
            provenance="none",
            note="no known listing surface; enter a model manually",
        ),
    )


def model_provenance(model: str | None, catalog: ModelCatalog) -> str:
    """Classify a configured model value for the settings screen."""
    if model is None:
        return "default"
    if model in catalog.models:
        return catalog.provenance if catalog.provenance != "none" else "manual"
    return "manual"

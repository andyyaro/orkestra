"""Unit tests: probe execution modes, caching, and budgets (fake adapter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.adapters.fake import FakeAdapter
from orkestra.capabilities.probes import run_probes
from orkestra.schemas.capability import CapabilityProbe
from orkestra.schemas.common import TaskKind
from orkestra.store import Database, Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(Database(tmp_path / "p.db"))


PROBE = CapabilityProbe(
    probe_id="unit-1",
    capability="structured_output",
    kind=TaskKind.PLAN,
    prompt='FAKE:structured:{"status": "ready"}',
    expected_kind="json",
    check='parsed == {"status": "ready"}',
)


class TestRunProbes:
    async def test_off_mode_runs_nothing(self, store: Store, tmp_path: Path) -> None:
        observations = await run_probes(
            {"alpha": FakeAdapter(agent_name="alpha")}, {"alpha": "1.0"}, store,
            tmp_path, mode="off", probes=[PROBE],
        )
        assert observations == []
        assert store.observations_for("alpha") == []

    async def test_live_probe_records_objective_result(
        self, store: Store, tmp_path: Path
    ) -> None:
        observations = await run_probes(
            {"alpha": FakeAdapter(agent_name="alpha")}, {"alpha": "1.0"}, store,
            tmp_path, mode="live", probes=[PROBE],
        )
        assert len(observations) == 1
        assert observations[0].objective_pass is True
        assert observations[0].source == "probe:unit-1"

    async def test_cached_mode_reuses_by_version(
        self, store: Store, tmp_path: Path
    ) -> None:
        adapters = {"alpha": FakeAdapter(agent_name="alpha")}
        await run_probes(adapters, {"alpha": "1.0"}, store, tmp_path,
                         mode="live", probes=[PROBE])
        cached = await run_probes(adapters, {"alpha": "1.0"}, store, tmp_path,
                                  mode="cached", probes=[PROBE])
        assert len(cached) == 1
        assert len(store.observations_for("alpha")) == 1  # nothing re-run
        # New version invalidates the cache.
        await run_probes(adapters, {"alpha": "2.0"}, store, tmp_path,
                         mode="cached", probes=[PROBE])
        assert len(store.observations_for("alpha")) == 2

    async def test_budget_limits_live_probes(self, store: Store, tmp_path: Path) -> None:
        probes = [
            PROBE.model_copy(update={"probe_id": f"unit-{i}"}) for i in range(5)
        ]
        observations = await run_probes(
            {"alpha": FakeAdapter(agent_name="alpha")}, {"alpha": "1.0"}, store,
            tmp_path, mode="live", budget=2, probes=probes,
        )
        assert len(observations) == 2

    async def test_failing_probe_recorded_as_failure(
        self, store: Store, tmp_path: Path
    ) -> None:
        probe = PROBE.model_copy(update={
            "probe_id": "unit-fail",
            "prompt": "FAKE:text:not json at all",
        })
        observations = await run_probes(
            {"alpha": FakeAdapter(agent_name="alpha")}, {"alpha": "1.0"}, store,
            tmp_path, mode="live", probes=[probe],
        )
        assert observations[0].objective_pass is False

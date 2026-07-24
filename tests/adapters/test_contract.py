"""Contract suite run against the fake adapter (reference implementation).

This exercises the full subprocess path: spawn, stream, parse, timeout,
cancellation, garbage handling — the same machinery real adapters use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orkestra.adapters.fake import FakeAdapter
from orkestra.adapters.testkit import run_contract_suite


@pytest.mark.e2e
async def test_fake_adapter_passes_contract(tmp_path: Path) -> None:
    report = await run_contract_suite(FakeAdapter(), tmp_path)
    assert report.passed, "\n" + report.summary()


async def test_external_detect_rejects_non_protocol_command(tmp_path: Path) -> None:
    from orkestra.adapters.external import ExternalAdapter

    adapter = ExternalAdapter(command=["echo", "hello"])
    info = await adapter.detect()
    assert not info.available
    assert "handshake" in info.detail


async def test_external_detect_missing_command() -> None:
    from orkestra.adapters.external import ExternalAdapter

    adapter = ExternalAdapter(command=["definitely-not-a-real-binary-xyz"])
    info = await adapter.detect()
    assert not info.available

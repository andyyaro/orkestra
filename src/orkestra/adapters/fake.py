"""Fake adapter — the scripted external adapter used by tests and offline mode."""

from __future__ import annotations

import sys

from orkestra.adapters.external import ExternalAdapter


class FakeAdapter(ExternalAdapter):
    adapter_id = "fake"

    def __init__(
        self,
        model: str | None = None,
        autonomy: str = "safe",
        agent_name: str = "fake",
    ) -> None:
        # model/autonomy accepted for constructor uniformity; unused.
        super().__init__(
            command=[
                sys.executable, "-m", "orkestra.adapters.fake_worker",
                "--agent-name", agent_name,
            ],
            name=agent_name,
        )
        self.adapter_id = "fake"

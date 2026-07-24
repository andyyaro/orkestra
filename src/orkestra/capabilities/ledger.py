"""Performance ledger → capability observations feedback loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from orkestra.capabilities.matrix import TASK_CAPABILITY
from orkestra.schemas.capability import CapabilityObservation

if TYPE_CHECKING:
    from orkestra.store import Store


def record_task_outcome(
    store: Store,
    run_id: str,
    agent: str,
    agent_version: str,
    task_id: str,
    task_kind: str,
    *,
    succeeded: bool,
    detail: str = "",
) -> None:
    """Record a real task outcome in both the ledger and the observation set.

    This is the §6.8 feedback loop: every completed task updates the
    evidence the matrix (and therefore future assignment ranking) is
    built from.
    """
    store.add_ledger_entry(
        run_id, agent, task_id, task_kind,
        "succeeded" if succeeded else "failed", detail,
    )
    capability = TASK_CAPABILITY.get(task_kind, "implementation")
    store.add_observation(
        CapabilityObservation(
            agent=agent,
            agent_version=agent_version,
            capability=capability,
            source=f"task:{task_id}",
            objective_pass=succeeded,
        )
    )

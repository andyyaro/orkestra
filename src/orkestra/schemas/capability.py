"""Capability probes, observations, matrix, and scores."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field

from orkestra.schemas.common import TaskKind, utc_now


class CapabilityProbe(BaseModel):
    """A bounded, safe exercise used to measure an agent capability."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    probe_id: str
    capability: str
    kind: TaskKind
    prompt: str
    expected_kind: str = "text"  # text | json | code
    check: str = ""
    """Deterministic check description, evaluated by the probe harness."""


class CapabilityObservation(BaseModel):
    """One measured outcome (probe result or real task outcome)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    agent: str
    agent_version: str = ""
    capability: str
    source: str  # probe:<id> | task:<id>
    objective_pass: bool | None = None
    judged_score: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_s: float = 0.0
    ts: datetime = Field(default_factory=utc_now)


class CapabilityScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    """Observation sources backing this score — scores without evidence are forbidden."""


class CapabilityMatrix(BaseModel):
    """agent -> capability -> evidenced score."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    scores: dict[str, dict[str, CapabilityScore]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)

    def score_for(self, agent: str, capability: str) -> CapabilityScore | None:
        return self.scores.get(agent, {}).get(capability)

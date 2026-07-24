"""Director decision envelopes.

Every director interaction is a schema-validated JSON document. The
kernel never executes free prose from the director.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orkestra.schemas.common import TaskKind
from orkestra.schemas.task import Assignment, TaskSpec


class DirectorAnalysis(BaseModel):
    """Project comprehension + capability demand profile."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    capability_demands: dict[str, float] = Field(default_factory=dict)
    """Capability name -> importance weight 0..1 (e.g. {"python": 0.9})."""


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskSpec
    assignment: Assignment


class DirectorPlan(BaseModel):
    """Full plan proposal: task DAG plus assignments."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    tasks: list[PlannedTask]
    notes: str = ""


class PlanChallenge(BaseModel):
    """Another agent's critique of a proposed plan."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    agent: str = ""
    concerns: list[str] = Field(default_factory=list)
    suggested_changes: list[str] = Field(default_factory=list)
    verdict: str = "accept"  # accept | revise


class ReviewVerdict(BaseModel):
    """Independent reviewer output for one task attempt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    approve: bool
    findings: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    severity: str = "none"  # none | low | medium | high | critical


class ReassignmentAdvice(BaseModel):
    """Director recommendation after repeated failures."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    reassign_to: str | None = None
    change_kind: TaskKind | None = None
    revised_instructions: str | None = None
    escalate_to_human: bool = False
    reason: str = ""

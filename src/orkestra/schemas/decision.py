"""Human decision records (human gates)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orkestra.schemas.common import utc_now


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    consequences: str = ""


class HumanDecision(BaseModel):
    """A persisted question only a human may answer."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    decision_id: str
    run_id: str
    task_id: str | None = None
    question: str
    why_blocked: str
    options: list[DecisionOption]
    recommendation: str = ""
    plain: str = ""
    """Plain-language explanation: cause → meaning → suggested next step."""
    unblocked_work: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    chosen_option: str | None = None
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.chosen_option is not None

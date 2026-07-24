"""Task, assignment, and brief contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from orkestra.schemas.common import TaskKind


class TaskSpec(BaseModel):
    """A node in the task DAG (as planned by the director or heuristics)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    key: str
    title: str
    kind: TaskKind
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    mutates_repo: bool = True


class Assignment(BaseModel):
    """Who does a task, who reviews it, who is the fallback."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    primary: str
    reviewers: list[str] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)
    rationale: str = ""


class TaskBrief(BaseModel):
    """What an adapter receives when dispatched (rendered by the kernel)."""

    task_id: str
    run_id: str
    title: str
    kind: TaskKind
    instructions: str
    cwd: str
    timeout_s: int
    json_schema: dict[str, object] | None = None
    resume_session_id: str | None = None

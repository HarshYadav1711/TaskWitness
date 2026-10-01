"""TaskWitness domain schemas: typed task contract for Phase 0."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActionType(str, Enum):
    prepare_followup = "prepare_followup"
    set_stage = "set_stage"
    send_message = "send_message"


class RunState(str, Enum):
    ready = "ready"
    planning = "planning"
    running = "running"
    paused = "paused"
    awaiting_approval = "awaiting_approval"
    verifying = "verifying"
    recovering = "recovering"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class Authority(BaseModel):
    """Autonomous permissions granted by the operator/goal.

    Authority is independent of requested actions. A TaskSpec may list
    send_message or set_stage while the corresponding authority flag is
    false; that means execution must seek human approval before the
    side effect, not that the plan is structurally invalid.
    """

    model_config = ConfigDict(extra="forbid")

    send_message: bool
    change_stage: bool


class TaskSpec(BaseModel):
    """Validated intent contract. Does not contain browser selectors,
    executable code, arbitrary URLs, or unrestricted tool instructions.
    """

    model_config = ConfigDict(extra="forbid")

    source_file: str
    role: str
    candidate_status: str
    actions: list[ActionType] = Field(min_length=1)
    target_stage: Optional[str] = None
    authority: Authority

    @field_validator("source_file", "role", "candidate_status")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank or whitespace-only")
        return value

    @field_validator("actions")
    @classmethod
    def _no_duplicate_actions(cls, actions: list[ActionType]) -> list[ActionType]:
        if len(actions) != len(set(actions)):
            raise ValueError("duplicate actions are not allowed")
        return actions

    @model_validator(mode="after")
    def _target_stage_consistency(self) -> "TaskSpec":
        has_set_stage = ActionType.set_stage in self.actions
        stage = self.target_stage

        if has_set_stage:
            if stage is None or not str(stage).strip():
                raise ValueError(
                    "target_stage is required and must be non-blank when set_stage is present"
                )
        else:
            if stage is not None:
                raise ValueError(
                    "target_stage must be absent/null when set_stage is not present"
                )

        return self

"""Interpretation result types. TaskSpec remains the only execution-intent schema."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from taskwitness.schemas import TaskSpec


class InterpretationStatus(str, Enum):
    ready = "ready"
    needs_clarification = "needs_clarification"
    invalid_model_output = "invalid_model_output"
    policy_rejected = "policy_rejected"
    model_error = "model_error"


class InterpretationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: InterpretationStatus
    original_goal: str
    task_spec: Optional[TaskSpec] = None
    clarification_question: Optional[str] = None
    error: Optional[str] = None


class ModelPlanEnvelope(BaseModel):
    """Untrusted structured model response before TaskSpec + policy validation."""

    model_config = ConfigDict(extra="forbid")

    status: str
    task_spec: Optional[dict] = None
    clarification_question: Optional[str] = None


class ModelClientError(Exception):
    """Provider/transport/auth failure. Message must never contain secrets."""

"""Goal interpreter: model → schema → policy → InterpretationResult."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from taskwitness.interpretation.client import ModelClient, ModelConfig, OpenAICompatibleClient
from taskwitness.interpretation.policy import PolicyRejection, validate_taskspec_policy
from taskwitness.interpretation.prompt import build_system_prompt, build_user_prompt
from taskwitness.interpretation.types import (
    InterpretationResult,
    InterpretationStatus,
    ModelClientError,
    ModelPlanEnvelope,
)
from taskwitness.schemas import TaskSpec


class GoalInterpreter:
    def __init__(self, client: ModelClient) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "GoalInterpreter":
        return cls(OpenAICompatibleClient(ModelConfig.from_env()))

    def interpret(self, goal: str) -> InterpretationResult:
        original = goal if goal is not None else ""
        if not str(original).strip():
            return InterpretationResult(
                status=InterpretationStatus.needs_clarification,
                original_goal=original,
                clarification_question=(
                    "What recruiting work should TaskWitness perform on candidates.csv "
                    "(prepare follow-ups, change TalentDesk stages, or both)?"
                ),
            )

        try:
            raw = self._client.complete_json(
                system=build_system_prompt(),
                user=build_user_prompt(str(original)),
            )
        except ModelClientError as exc:
            return InterpretationResult(
                status=InterpretationStatus.model_error,
                original_goal=str(original),
                error=str(exc),
            )

        return self._finalize(str(original), raw)

    def interpret_raw(self, goal: str, raw: dict[str, Any]) -> InterpretationResult:
        """Deterministic path for tests: skip the live model client."""
        return self._finalize(goal, raw)

    def _finalize(self, goal: str, raw: Any) -> InterpretationResult:
        if not isinstance(raw, dict):
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error="model output root must be a JSON object",
            )

        banned = {
            "python",
            "javascript",
            "code",
            "selector",
            "xpath",
            "css",
            "url",
            "shell",
            "sql",
            "playwright",
            "browser_instruction",
            "tool_call",
            "reasoning",
            "thoughts",
            "scratchpad",
            "analysis",
        }
        lowered = {str(k).lower() for k in raw.keys()}
        if banned & lowered:
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error="model output contained unsupported executable or reasoning fields",
            )

        try:
            envelope = ModelPlanEnvelope.model_validate(raw)
        except ValidationError as exc:
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error=f"envelope validation failed: {_brief_validation(exc)}",
            )

        status = envelope.status.strip().lower()
        if status == InterpretationStatus.needs_clarification.value:
            question = (envelope.clarification_question or "").strip()
            if not question:
                return InterpretationResult(
                    status=InterpretationStatus.invalid_model_output,
                    original_goal=goal,
                    error="needs_clarification requires clarification_question",
                )
            return InterpretationResult(
                status=InterpretationStatus.needs_clarification,
                original_goal=goal,
                clarification_question=question,
            )

        if status != InterpretationStatus.ready.value:
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error=f"unsupported interpretation status {envelope.status!r}",
            )

        if envelope.task_spec is None:
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error="ready status requires task_spec",
            )

        if not isinstance(envelope.task_spec, dict):
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error="task_spec must be an object",
            )

        try:
            spec = TaskSpec.model_validate(envelope.task_spec)
        except ValidationError as exc:
            return InterpretationResult(
                status=InterpretationStatus.invalid_model_output,
                original_goal=goal,
                error=f"TaskSpec validation failed: {_brief_validation(exc)}",
            )

        try:
            approved = validate_taskspec_policy(spec)
        except PolicyRejection as exc:
            return InterpretationResult(
                status=InterpretationStatus.policy_rejected,
                original_goal=goal,
                error=exc.message,
            )

        return InterpretationResult(
            status=InterpretationStatus.ready,
            original_goal=goal,
            task_spec=approved,
        )


def _brief_validation(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid"
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "invalid")
    return f"{loc}: {msg}" if loc else str(msg)

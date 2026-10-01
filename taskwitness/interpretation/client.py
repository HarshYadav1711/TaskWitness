"""OpenAI-compatible model client boundary for goal interpretation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from taskwitness.interpretation.types import ModelClientError


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    model: str
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "ModelConfig":
        api_key = (os.environ.get("LLM_API_KEY") or "").strip()
        model = (os.environ.get("LLM_MODEL") or "").strip()
        base_url = (os.environ.get("LLM_BASE_URL") or "").strip() or None
        if not api_key:
            raise ModelClientError(
                "LLM_API_KEY is not configured. Live interpretation requires model credentials."
            )
        if not model:
            raise ModelClientError(
                "LLM_MODEL is not configured. Live interpretation requires a model name."
            )
        return cls(api_key=api_key, model=model, base_url=base_url)


class ModelClient(Protocol):
    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Return parsed JSON object from the model. Raises ModelClientError on failure."""


class OpenAICompatibleClient:
    """Thin OpenAI SDK wrapper. No retries for semantic failures."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise ModelClientError(
                "openai package is not installed. pip install openai"
            ) from exc

        kwargs: dict[str, Any] = {"api_key": self._config.api_key}
        if self._config.base_url:
            kwargs["base_url"] = self._config.base_url

        try:
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=self._config.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:  # noqa: BLE001 — map all provider errors
            raise ModelClientError(_safe_provider_message(exc)) from None

        try:
            content = response.choices[0].message.content or ""
            data = json.loads(content)
        except (IndexError, AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise ModelClientError(
                "model returned malformed or non-JSON structured output"
            ) from exc

        if not isinstance(data, dict):
            raise ModelClientError("model JSON root must be an object")
        return data


class FakeModelClient:
    """Deterministic test double. Returns a fixed payload or raises."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        raw_text: str | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.raw_text = raw_text
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.error is not None:
            if isinstance(self.error, ModelClientError):
                raise self.error
            raise ModelClientError(str(self.error)) from self.error
        if self.raw_text is not None:
            raise ModelClientError("model returned malformed or non-JSON structured output")
        if self.payload is None:
            raise ModelClientError("FakeModelClient has no payload")
        return self.payload


def _safe_provider_message(exc: Exception) -> str:
    text = str(exc)
    key = (os.environ.get("LLM_API_KEY") or "").strip()
    if key and key in text:
        text = text.replace(key, "[redacted]")
    if len(text) > 300:
        text = text[:300] + "..."
    return f"model provider error: {text}"

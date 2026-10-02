"""Deterministic action_key generation for journaled side effects.

action_key identifies the logical TaskWitness journal effect within a run.
operation_id is the separate TeamMail business identity carried into the app.

Normalization rules:
- JSON object with sorted keys, compact separators
- strings stripped
- include run_id so keys are unique per durable run without colliding across runs
- payload is action-specific (see helpers below)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a sorted, stripped, JSON-stable payload dict."""

    def _norm(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
        if isinstance(value, list):
            return [_norm(v) for v in value]
        return value

    return _norm(payload)  # type: ignore[return-value]


def make_action_key(
    *,
    run_id: str,
    action_type: str,
    candidate_id: str,
    payload: dict[str, Any],
) -> str:
    material = {
        "run_id": run_id.strip(),
        "action_type": action_type.strip(),
        "candidate_id": candidate_id.strip(),
        "payload": normalize_payload(payload),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def set_stage_payload(*, target_stage: str) -> dict[str, str]:
    return {"target_stage": target_stage.strip()}


def prepare_followup_payload(
    *,
    operation_id: str,
    recipient: str,
    role: str,
) -> dict[str, str]:
    return {
        "operation_id": operation_id.strip(),
        "recipient": recipient.strip().lower(),
        "role": role.strip().lower(),
    }


def send_message_payload(*, operation_id: str) -> dict[str, str]:
    return {"operation_id": operation_id.strip()}

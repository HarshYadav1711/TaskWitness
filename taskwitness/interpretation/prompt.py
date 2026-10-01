"""Interpretation prompt contract for the controlled recruiting domain."""

from __future__ import annotations

from taskwitness.interpretation.policy import (
    APPROVED_SOURCE,
    PIPELINE_STAGES,
    supported_roles,
    supported_statuses,
)
from taskwitness.schemas import ActionType


def build_system_prompt() -> str:
    roles = ", ".join(sorted(supported_roles()))
    statuses = ", ".join(sorted(supported_statuses()))
    stages = ", ".join(sorted(PIPELINE_STAGES))
    actions = ", ".join(a.value for a in ActionType)

    return f"""You interpret plain-English recruiting goals for TaskWitness.

You are NOT a browser operator, authority engine, executor, verifier, or recovery system.
Return ONLY a JSON object. Never return Python, JavaScript, selectors, URLs, shell, SQL, or tool calls.

Controlled domain:
- source_file must be exactly "{APPROVED_SOURCE}"
- supported roles: {roles}
- supported candidate_status values: {statuses}
- supported target_stage values (TalentDesk): {stages}
- supported actions: {actions}

Response JSON schema:
{{
  "status": "ready" | "needs_clarification",
  "task_spec": null | {{
    "source_file": "{APPROVED_SOURCE}",
    "role": "<supported role>",
    "candidate_status": "<supported status>",
    "actions": ["prepare_followup" and/or "set_stage" and/or "send_message"],
    "target_stage": "<supported stage>" | null,
    "authority": {{
      "send_message": true|false,
      "change_stage": true|false
    }}
  }},
  "clarification_question": null | "<short question>"
}}

TaskSpec rules:
- actions is a non-empty list with no duplicates.
- If set_stage is present, target_stage is required and must be a supported stage.
- If set_stage is absent, target_stage must be null.
- Authority is separate from requested actions.
- If the user asks to prepare a message but requires confirmation before sending, include send_message in actions and set authority.send_message=false.
- If the user asks to change stage but requires confirmation first, include set_stage and target_stage, and set authority.change_stage=false.
- Do not omit a requested action merely because confirmation is required.
- Do not invent LinkedIn, Gmail, web search, or other unsupported capabilities.
- Underspecified goals such as "handle the candidates" must return needs_clarification with a concrete question about supported choices (prepare follow-ups, change stage, or both).
- Unsupported external-system goals must return needs_clarification explaining only controlled TalentDesk/TeamMail capabilities are supported.
- Be conservative: do not grant authority.send_message=true or authority.change_stage=true unless the user clearly authorizes autonomous performance of that side effect.
- Prefer clarification over guessing.
"""


def build_user_prompt(goal: str) -> str:
    return (
        "Interpret the following recruiting goal for the controlled TaskWitness environment.\n"
        "Return JSON only.\n\n"
        f"GOAL:\n{goal.strip()}\n"
    )

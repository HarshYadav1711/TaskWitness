# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phases 0–3 locked the contract, synthetic apps, Playwright execution, and NL→TaskSpec interpretation. Phase 4 adds the human-control layer between validated intent and side effects.

## Architecture decisions

AI is used only to interpret intent. The deterministic workflow remains separate and is never driven by raw model text. Even with provider JSON mode, local Pydantic `TaskSpec` validation is required because provider structure is not a trust boundary. Ambiguous goals stop with clarification instead of guessing capabilities. LangChain/LangGraph were not introduced: a thin OpenAI-compatible client plus explicit policy code is enough for this assessment. Authority remains a separate field from requested actions so “ask before send/stage” stays representable without dropping the action.

Phase 4 keeps approval behind an `ApprovalProvider` so terminal input stays out of business logic and Phase 7 can replace it with a UI. Progress uses a small in-memory sink/callback—no Redis, WebSockets, or queues. No new third-party runtime dependency was added for control.

## Reliability and recovery

TeamMail supports unique `operation_id`. Draft→send preserves the same operation id. The synthetic ambiguous-send fault may still interrupt acknowledgement after commit; Phase 4 surfaces that as unknown/failed and does **not** blindly retry. Durable journal + inspect-before-retry recovery belong to Phase 5.

## Human control and authority

Requested actions and authority flags are independent. When an action is requested with false authority, Phase 4 requests approval immediately before the side effect. Approvals are action-scoped (one concrete candidate/operation), not a permanent rewrite of `TaskSpec.authority`. Rejecting a send leaves the draft intact, preserves prior stage work, and yields `PARTIAL` rather than a false `FAILED`.

Pause is **cooperative**: the workflow stops at safe checkpoints before the next external side effect. It does not interrupt an in-flight Playwright action or kill Chromium. Control/approval/progress state is in-memory only for Phase 4.

## Verification

Immediate UI confirmation supports automation reliability. Independent postcondition/evidence verification is not implemented yet.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

No durable TaskWitness journal, crash resume, or final operator UI yet. Live interpretation quality depends on the configured model; unit tests use a fake client and do not claim live accuracy percentages. Pause/approval state does not survive process restart.

## What I would build next

Phase 5 — durable journal and safe ambiguous-send recovery, per `docs/PHASES.md`.

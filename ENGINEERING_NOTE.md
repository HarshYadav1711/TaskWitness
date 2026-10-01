# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phase 0 locked the typed contract. Phase 1 added synthetic apps. Phase 2 added Playwright operation. Phase 3 adds natural-language interpretation into the same `TaskSpec` boundary.

## Architecture decisions

AI is used only to interpret intent. The deterministic workflow remains separate and is never driven by raw model text. Even with provider JSON mode, local Pydantic `TaskSpec` validation is required because provider structure is not a trust boundary. Ambiguous goals stop with clarification instead of guessing capabilities. LangChain/LangGraph were not introduced: a thin OpenAI-compatible client plus explicit policy code is enough for this assessment. Authority remains a separate field from requested actions so “ask before send/stage” stays representable without dropping the action.

## Reliability and recovery

TeamMail supports unique `operation_id`. Phase 2/3 reuses existing drafts for the same operation id. Ambiguous-send recovery and the TaskWitness journal are not implemented yet.

## Human control and authority

Requested actions and authority flags are independent. Phase 3 may interpret `authority.send_message=true`, but execution still defers all sends until Phase 4. False `change_stage` authority keeps stage mutation deferred.

## Verification

Immediate UI confirmation supports automation reliability. Independent postcondition/evidence verification is not implemented yet.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

No approval UI, journal, or evidence packs yet. Live interpretation quality depends on the configured model; unit tests use a fake client and do not claim live accuracy percentages.

## What I would build next

Phase 4 — authority gates and execution controls (approval / pause), per `docs/PHASES.md`.

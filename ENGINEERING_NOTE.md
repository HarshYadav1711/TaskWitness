# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phases 0–6 locked the contract, synthetic apps, Playwright execution, NL→TaskSpec interpretation, human control, durable journal/recovery, and independent verification/evidence. Phase 7 adds the local operator console that exercises those backends without reimplementing them in JavaScript.

## Architecture decisions

AI is used only to interpret intent. The deterministic workflow remains separate and is never driven by raw model text. Authority remains a separate field from requested actions. Approvals go through `ApprovalProvider`; the operator UI uses `WebApprovalProvider` so the same workflow boundary waits for a human decision.

Vanilla HTML/CSS/JS was chosen for the operator surface: FastAPI already serves the synthetic apps, and a frontend framework would add assessment overhead without changing control semantics. The browser polls `GET /api/runs/{id}` about every 500ms instead of WebSockets—adequate for a single local operator and easier to reason about under approval/pause waits.

Live operator state lives in an in-memory registry (one active run). Durable effect history stays in the TaskWitness journal. That split keeps UI coordination simple while preserving Phase 5 recovery durability. Approval IDs are validated and resolved exactly once on the server; disabling a button is not the security boundary.

The UI separates **execution** outcome from **verification** outcome. “Goal verified” appears only when `verified_complete` is true after a fresh verification pass.

## Reliability and recovery

Failed browser acknowledgement is not treated as proof the business side effect failed. Ambiguous sends become `UNKNOWN`, then TaskWitness inspects visible TeamMail Sent state by stable `operation_id` before any retry. Exactly one match recovers without resending. Multiple matches or unavailable inspection block rather than guess.

## Human control and authority

Approvals remain action-scoped and do not mutate `TaskSpec.authority`. Approval precedes write-ahead `IN_PROGRESS`; rejection records `REJECTED` with `attempt_count=0`.

## Verification

Execution output is not accepted as proof of final business state. After the worker finishes execution it closes the execution browser, opens a fresh verification session, and writes evidence. Rejected sends can pass a no-send safety check while remaining incomplete.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

Validated Plan Demo Mode proves operator control/runtime without live model credentials; it does not claim live natural-language interpretation quality. One active run at a time. Operator UI state does not survive operator-server restart. Phase 8 assessment harness runs assignment scenarios through the operator UI with isolated processes; live-provider pre-submission checks remain separate and unresolved until credentials are actually used.

## What I would build next

Phase 9 — hardening and adversarial review, per `docs/PHASES.md`.

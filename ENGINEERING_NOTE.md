# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phases 0–4 locked the contract, synthetic apps, Playwright execution, NL→TaskSpec interpretation, and human control. Phase 5 adds a durable local journal and safe recovery for uncertain side effects.

## Architecture decisions

AI is used only to interpret intent. The deterministic workflow remains separate and is never driven by raw model text. Authority remains a separate field from requested actions. Phase 4 keeps approval behind an `ApprovalProvider`. Phase 5 journals effectful actions with write-ahead recording before browser mutation so acknowledgement loss cannot erase the fact that an attempt started.

SQLite via the standard library is sufficient for local assessment journaling. No ORM, Redis, or distributed recovery stack was introduced. The journal is intentionally separate from `demo_env` persistence.

## Reliability and recovery

Failed browser acknowledgement is not treated as proof the business side effect failed. Ambiguous sends become `UNKNOWN`, then TaskWitness inspects visible TeamMail Sent state by stable `operation_id` before any retry. Exactly one match recovers without resending. Multiple matches or unavailable inspection block rather than guess. TeamMail’s uniqueness constraint is defense-in-depth; TaskWitness still performs independent UI inspection. `action_key` (journal identity) and `operation_id` (application identity) remain distinct.

## Human control and authority

Approvals remain action-scoped and do not mutate `TaskSpec.authority`. Approval precedes write-ahead `IN_PROGRESS`; rejection records `REJECTED` with `attempt_count=0`.

## Verification

Immediate UI confirmation and Phase 5 recovery inspection support safe continuation. Independent whole-goal postcondition/evidence verification is Phase 6.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

No final evidence packs or operator UI yet. Journal survives reopen for UNKNOWN reconciliation; full arbitrary mid-browser crash resume of every Playwright step is not claimed. Live interpretation quality depends on the configured model.

## What I would build next

Phase 6 — independent verification and evidence, per `docs/PHASES.md`.

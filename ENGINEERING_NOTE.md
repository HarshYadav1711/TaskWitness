# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phase 0 locked the typed contract. Phase 1 added synthetic TalentDesk/TeamMail. Phase 2 adds deterministic Playwright operation of those apps through their visible UIs.

Controlled synthetic applications are used so the assessment can demonstrate visible multi-step computer use without production ATS/email integrations, real candidate data, or outbound mail risk.

## Architecture decisions

Documented in `docs/ARCHITECTURE.md`. Direct Playwright was chosen instead of a browser-agent framework so every click/fill/assertion stays explicit, reviewable, and testable. LLM interpretation is intentionally absent in Phase 2: the browser workflow is driven by explicit `WorkflowConfig` / optional TaskSpec mapping, proving computer operation before adding untrusted model output. UI side effects (stage changes, draft saves) must go through Playwright adapters—not SQLite or internal mutation helpers.

## Reliability and recovery

TeamMail supports unique `operation_id` and rejects duplicate sent records for the same id. Phase 2 reuses an existing draft when the same deterministic operation id already appears. Ambiguous-send recovery and the TaskWitness journal are not implemented yet.

## Human control and authority

`TaskSpec.actions` and `TaskSpec.authority` are independent. Phase 2 never autonomously sends mail; `send_message` is deferred until the authority phase. Runtime approval gates are not implemented yet.

## Verification

Immediate UI confirmation after an action (e.g. “Draft saved”) supports reliable automation. The future independent postcondition/evidence subsystem is not implemented yet.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

Phase 2: deterministic browser workflow only. No NL interpreter, authority UI, journal, or evidence packs. Assessment is intentionally time-boxed.

## What I would build next

Phase 3 — natural-language goal interpretation into validated `TaskSpec`, per `docs/PHASES.md`.

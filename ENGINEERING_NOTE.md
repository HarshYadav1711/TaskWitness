# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phase 0 locked context, architecture, and the typed task contract. Phase 1 adds synthetic TalentDesk and TeamMail so later browser operation has real, inspectable application state.

Controlled synthetic applications are used so the assessment can demonstrate visible multi-step computer use without production ATS/email integrations, real candidate data, or outbound mail risk.

## Architecture decisions

Documented in `docs/ARCHITECTURE.md`. One FastAPI process hosts two app surfaces; SQLite (`sqlite3`) holds demo-app state only. That store is intentionally separate from the future TaskWitness execution journal. No production Gmail/Outlook/ATS connectors.

## Reliability and recovery

TeamMail supports unique `operation_id` and rejects duplicate sent records for the same id. A test-only one-shot `fail_after_send_commit_once` can interrupt acknowledgement after commit. TaskWitness recovery logic is not implemented yet.

## Human control and authority

`TaskSpec.actions` and `TaskSpec.authority` are independent. Autonomous send may be unauthorized while still present as requested work, requiring later approval. Runtime gates not implemented yet.

## Verification

Completion will require postconditions against application state—not LLM claims or exception-free returns. Not implemented yet.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

Phase 1: synthetic apps only. No TaskWitness browser operator, journal, interpreter, or operator UI. Assessment is intentionally time-boxed.

## What I would build next

Phase 2 — deterministic Playwright execution against TalentDesk/TeamMail, per `docs/PHASES.md`.

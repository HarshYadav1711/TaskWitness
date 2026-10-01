# Engineering Note

Current status: this note is being completed alongside implementation and will be finalized for submission.

## Problem and approach

TaskWitness addresses a controlled recruiting-ops workflow where a plain-English goal must become authorized, deterministic computer operations with independent verification. Phase 0 locks context, architecture, and the typed task contract before any side-effecting product code.

## Architecture decisions

Documented in `docs/ARCHITECTURE.md`. Phase 0 implements only the Pydantic `TaskSpec` boundary (intent + separate authority). Later: Playwright for visible execution, SQLite journal, FastAPI + HTML UI, LLM for interpretation only.

## Reliability and recovery

Planned: journalled effects; inspect-before-retry on ambiguous outcomes; no duplicate sends. Not implemented yet.

## Human control and authority

`TaskSpec.actions` and `TaskSpec.authority` are independent. Autonomous send may be unauthorized while still present as requested work, requiring later approval. Runtime gates not implemented yet.

## Verification

Completion will require postconditions against application state—not LLM claims or exception-free returns. Not implemented yet.

## Personal contribution

_To be completed for submission._

## AI and tools used

_To be completed for submission._

## Limitations

Phase 0 only: no browser operator, apps, journal, or UI. Assessment is intentionally time-boxed.

## What I would build next

Phase 1 — synthetic TalentDesk and TeamMail environment, per `docs/PHASES.md`.

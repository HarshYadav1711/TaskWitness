# Demo Runbook

## Preconditions

- Phase 0 complete: docs, schemas, fixtures, and schema tests available.
- Later phases required for a full live demo: synthetic apps, Playwright execution, interpreter, authority UI, journal/recovery, verification/evidence, operator UI.
- Use synthetic data only (`data/candidates.csv`, `example.test` addresses).
- Reset controlled apps to a known seed state before each scenario (once apps exist).

## Scenario 1 — Base workflow

**Goal (approx.):** From `candidates.csv`, process shortlisted AI Engineering candidates. Prepare interview follow-ups, move matching candidates to Interview Ready, ask before sending any message.

**Expected behavior:** Matching candidates identified; TalentDesk opened and stages updated when authorized; TeamMail drafts prepared; send gated on approval; postconditions verified; evidence produced.

**Fixture plan:** `examples/base-plan.json`

## Scenario 2 — Goal variation

**Goal (approx.):** Process shortlisted Backend Engineering candidates. Prepare follow-ups only. Do not send messages and do not change stages.

**Expected behavior:** Same codebase; different goal/plan only. Follow-ups prepared; no stage changes; no sends.

**Fixture plan:** `examples/variation-plan.json`

## Scenario 3 — Failure and recovery

**Expected behavior:** Send is attempted; message persists; acknowledgement is interrupted. Operator does not immediately retry Send. Inspection finds the existing message; duplicate retry suppressed; run records recovery.

## Evidence to show

- Visible application interaction (once implemented).
- Execution trace / run state including approval and recovery when applicable.
- Independent verification status.
- Evidence artifacts reflecting resulting app state.

## Cleanup/reset

Restore TalentDesk stages and TeamMail mailbox to seed data before re-running scenarios (procedure to be documented when apps land in Phase 1+).

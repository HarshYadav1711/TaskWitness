# Demo Runbook

## Preconditions

- Phase 1 complete: TalentDesk and TeamMail available locally.
- Use synthetic data only (`data/candidates.csv`, `example.test` addresses).
- Reset before each scenario:

```bash
python -m demo_env.seed --reset
python -m demo_env
```

- TalentDesk: http://127.0.0.1:8000/talentdesk
- TeamMail: http://127.0.0.1:8000/teammail

Later phases are still required for automated TaskWitness operation, authority UI, journal/recovery, verification/evidence, and the operator UI.

## Scenario 1 — Base workflow

**Goal (approx.):** From `candidates.csv`, process shortlisted AI Engineering candidates. Prepare interview follow-ups, move matching candidates to Interview Ready, ask before sending any message.

**Expected behavior (once TaskWitness execution exists):** Matching candidates identified; TalentDesk opened and stages updated when authorized; TeamMail drafts prepared; send gated on approval; postconditions verified; evidence produced.

**Manual Phase 1 check:** Filter AI Engineering / Shortlisted candidates in TalentDesk; change a stage; compose and save a TeamMail draft.

**Fixture plan:** `examples/base-plan.json`

## Scenario 2 — Goal variation

**Goal (approx.):** Process shortlisted Backend Engineering candidates. Prepare follow-ups only. Do not send messages and do not change stages.

**Expected behavior:** Same codebase; different goal/plan only. Follow-ups prepared; no stage changes; no sends.

**Fixture plan:** `examples/variation-plan.json`

## Scenario 3 — Failure and recovery

**Expected behavior (later phases):** Send is attempted; message persists; acknowledgement is interrupted. Operator does not immediately retry Send. Inspection finds the existing message; duplicate retry suppressed; run records recovery.

TeamMail’s test-only `fail_after_send_commit_once` seam exists for that future demo; TaskWitness recovery is not implemented in Phase 1.

## Evidence to show

- Visible application interaction (TaskWitness automation: later).
- Manual Phase 1: TalentDesk stage change and TeamMail Sent inspection.
- Execution trace / run state including approval and recovery when applicable (later).
- Independent verification status (later).

## Cleanup/reset

```bash
python -m demo_env.seed --reset
```

Restores candidates from `data/candidates.csv` and clears TeamMail drafts/sent messages.

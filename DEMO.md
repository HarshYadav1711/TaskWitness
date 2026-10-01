# Demo Runbook

## Preconditions

- Phase 2 complete: TalentDesk/TeamMail + Playwright workflow available.
- Use synthetic data only (`data/candidates.csv`, `example.test` addresses).
- Install Chromium once: `python -m playwright install chromium`
- Reset and start apps before each scenario:

```bash
python -m demo_env.seed --reset
python -m demo_env
```

- TalentDesk: http://127.0.0.1:8000/talentdesk
- TeamMail: http://127.0.0.1:8000/teammail

## Deterministic headed browser run (Phase 2)

In a second terminal (demo server already running):

```bash
python -m taskwitness.browser_demo ^
  --role "AI Engineering" ^
  --status "Shortlisted" ^
  --target-stage "Interview Ready" ^
  --prepare-followups ^
  --headed ^
  --slow-mo 100
```

Expected: Chromium opens; TalentDesk filter/detail/stage updates; TeamMail compose + draft save for matching candidates; **no sends**.

## Scenario 1 — Base workflow

**Goal (approx.):** From `candidates.csv`, process shortlisted AI Engineering candidates. Prepare interview follow-ups, move matching candidates to Interview Ready, ask before sending any message.

**Phase 2 behavior:** Stage updates + draft preparation only. Sending awaits the authority phase.

**Fixture plan:** `examples/base-plan.json` (optional `--from-taskspec`; `send_message` deferred).

## Scenario 2 — Goal variation

**Goal (approx.):** Process shortlisted Backend Engineering candidates. Prepare follow-ups only. Do not send messages and do not change stages.

```bash
python -m taskwitness.browser_demo --role "Backend Engineering" --status "Shortlisted" --prepare-followups --headed
```

(Omit `--target-stage` for no stage changes.)

**Fixture plan:** `examples/variation-plan.json`

## Scenario 3 — Failure and recovery

**Expected behavior (later phases):** Ambiguous send acknowledgement; inspect before retry; suppress duplicate send.

TeamMail’s test-only fault seam exists; TaskWitness recovery is not implemented in Phase 2.

## Evidence to show

- Visible Chromium interaction with TalentDesk and TeamMail.
- Drafts created; Sent empty for the Phase 2 workflow.
- Structured JSON result from `browser_demo`.

## Cleanup/reset

```bash
python -m demo_env.seed --reset
```

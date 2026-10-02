# Demo Runbook

## Preconditions

- Phase 8 complete: product through operator UI + assessment acceptance harness.
- Synthetic data only (`data/candidates.csv`, `example.test`).
- Install Chromium once: `python -m playwright install chromium`
- For live interpretation, set `LLM_API_KEY` and `LLM_MODEL` (optional `LLM_BASE_URL`).

Live-provider interpretation check for submission/video: **pending** until credentials are used for a real pass (base, paraphrase, variation, ask-before-send/stage, underspecified, unsupported). Do not invent results.

## Phase 8 assessment scenarios

Deterministic (Validated Plan Demo Mode — not live NL):

```bash
python -m taskwitness.assessment_accept --scenario base
python -m taskwitness.assessment_accept --scenario variation
python -m taskwitness.assessment_accept --scenario recovery
python -m taskwitness.assessment_accept --scenario rejection
python -m taskwitness.assessment_accept --scenario pause
```

Headed rehearsal for the three required demos:

```bash
python -m taskwitness.assessment_accept --scenario base --headed --slow-mo 60
python -m taskwitness.assessment_accept --scenario variation --headed --slow-mo 40
python -m taskwitness.assessment_accept --scenario recovery --headed --slow-mo 60
```

The harness resets synthetic state, starts isolated demo_env + operator processes, drives the operator UI, asserts outcomes, and cleans up.

## Phase 7 operator UI (headed)

If running the operator manually (outside the assessment harness), reset and start apps first:

```bash
python -m demo_env.seed --reset
python -m demo_env
```

Start the operator (Validated Plan Demo Mode — development only; not live NL):

```bash
python -m taskwitness.operator_demo --demo-plan examples/base-plan.json --headed --slow-mo 80
```

Open http://127.0.0.1:8010/operator

### Approval path

1. Confirm the **Validated Plan Demo Mode** banner.
2. Click **Start validated plan**.
3. Watch headed Chromium operate TalentDesk / TeamMail.
4. Observe execution trace updates in the operator UI.
5. When **Approval required** appears, review action / candidate / target / reason.
6. Click **Approve and continue** for each send.
7. Wait for verification panel → **VERIFIED** and “Goal verified”.
8. Confirm evidence path under `evidence/…` and TaskSpec authority still `send_message=false`.

### Rejection path

Reset apps, restart operator if needed, start validated plan, **Reject** sends.

Expect: Execution **PARTIAL**, Verification **INCOMPLETE**, incomplete work listed, no matching Sent artifacts, wording is not “Goal verified”.

### Pause / resume

With `--slow-mo` for pacing: during a run click **Pause**, wait until state becomes **PAUSED** at a safe checkpoint (after current atomic UI operation), confirm no next side effect, click **Resume**, confirm continuation.

### Recovery through UI (optional)

```bash
python -m demo_env.seed --reset
# arm fault via recovery setup, then:
python -m taskwitness.operator_demo --demo-plan examples/base-plan.json --headed
```

Or use `python -m taskwitness.recovery_demo ...` then verify; for UI recovery, arm `fail_after_send_commit_once` in demo_env before starting the operator run. Trace should show uncertain acknowledgement → Sent inspect → recovered without retry → verification passed.

## Phase 6 independent verification + evidence (headed)

### Base: execute then verify

```bash
python -m demo_env.seed --reset
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --reset-journal --verify --headed
```

Or execute, note `run_id` from JSON output, then:

```bash
python -m taskwitness.verify_demo --run-id <RUN_ID> --headed
```

Confirm: fresh browser inspection; `verified_complete=true`; evidence under `evidence/<run_id>/` with `summary.md` saying VERIFIED; screenshots for TalentDesk stages and TeamMail Sent; `manifest.json` hashes validate.

### Recovery + verification

```bash
python -m demo_env.seed --reset
python -m taskwitness.recovery_demo --from-taskspec examples/base-plan.json --reset-journal --verify --headed
```

Confirm evidence shows UNKNOWN→RECOVERED, `attempt_count=1`, exactly one Sent per operation, final send postcondition PASSED, overall VERIFIED.

### Incomplete / rejection

```bash
python -m demo_env.seed --reset
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --reject-all --verify --headed
```

Confirm: Result INCOMPLETE; stage/draft completed; send not completed; no matching Sent; `verified_complete=false`.

Evidence packages are generated runtime artifacts under `evidence/` (gitignored). Do not commit them.

## Phase 5 ambiguous-send recovery (headed)

Clean TaskWitness journal (does not reset demo_env):

```bash
python -m taskwitness.recovery_demo --from-taskspec examples/base-plan.json --reset-journal --headed
```

This arms the synthetic `fail_after_send_commit_once` seam (test/setup), then:

1. prepares follow-ups / stages per TaskSpec;
2. requests approval when `send_message` authority is false;
3. clicks Send through TeamMail UI;
4. TeamMail persists the message then interrupts acknowledgement;
5. journal records `UNKNOWN`;
6. recovery opens Sent, finds the same `operation_id` exactly once;
7. marks `RECOVERED` without a second Send;
8. prints journal transitions (`attempt_count=1`).

Inspect Sent afterward: exactly one message per logical operation.

Journal location: `.taskwitness/journal.sqlite3` (override with `TASKWITNESS_JOURNAL`).

## Phase 4 control harness (headed)

Canonical base TaskSpec (`prepare_followup` + `set_stage` + `send_message`, `change_stage=true`, `send_message=false`):

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --headed
```

Expected: TalentDesk identity check → stage update without approval → TeamMail draft → terminal approval before Send → approve → Sent shows the message.

Rejection case:

```bash
python -m demo_env.seed --reset
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --reject-all --headed
```

Expected: stage + draft succeed; send incomplete; drafts remain; Sent empty for rejected messages; `run_state` is `partial`. TaskSpec authority flags remain false.

Non-interactive approve-all:

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --headed
```

Optional pause/resume console (worker thread; type `p` then `r`):

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --console-control --headed
```

Control state is in-memory only. This is not the final operator UI.

## Natural-language interpretation (no browser)

```bash
python -m taskwitness.interpret_goal --goal "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask me before sending any message."
```

Variation:

```bash
python -m taskwitness.interpret_goal --goal "Process shortlisted Backend Engineering candidates from candidates.csv. Prepare follow-ups only. Do not send messages and do not change candidate stages."
```

Optional live fixture eval (no Playwright):

```bash
python -m taskwitness.interpret_eval
```

## Optional: interpret then execute

Demo server must be running.

```bash
python -m taskwitness.interpret_goal --execute --approve-all --headed --goal "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask me before sending any message."
```

## Deterministic headed browser run (no model, drafts only)

```bash
python -m taskwitness.browser_demo ^
  --role "AI Engineering" ^
  --status "Shortlisted" ^
  --target-stage "Interview Ready" ^
  --prepare-followups ^
  --headed
```

## Scenario notes

1. **Base** — AI Engineering shortlisted: prepare follow-up + set Interview Ready + ask before send (Phase 4 approval).
2. **Variation** — Backend Engineering shortlisted: prepare follow-ups only.
3. **Failure/recovery** — Phase 5 ambiguous send: journal UNKNOWN → inspect Sent → RECOVERED; no duplicate.

## Cleanup/reset

```bash
python -m demo_env.seed --reset
```

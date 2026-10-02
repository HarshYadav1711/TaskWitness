# Demo Runbook

## Preconditions

- Phase 4 complete: NL interpretation + Playwright workflow + human control.
- Synthetic data only (`data/candidates.csv`, `example.test`).
- Install Chromium once: `python -m playwright install chromium`
- For live interpretation, set `LLM_API_KEY` and `LLM_MODEL` (optional `LLM_BASE_URL`).

Reset and start apps when executing browser work:

```bash
python -m demo_env.seed --reset
python -m demo_env
```

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
3. **Failure/recovery** — later phases (ambiguous send). Phase 4 does not recover it.

## Cleanup/reset

```bash
python -m demo_env.seed --reset
```

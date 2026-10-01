# Demo Runbook

## Preconditions

- Phase 3 complete: NL interpretation + Playwright workflow available.
- Synthetic data only (`data/candidates.csv`, `example.test`).
- Install Chromium once: `python -m playwright install chromium`
- For live interpretation, set `LLM_API_KEY` and `LLM_MODEL` (optional `LLM_BASE_URL`).

Reset and start apps when executing browser work:

```bash
python -m demo_env.seed --reset
python -m demo_env
```

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

## Optional: interpret then execute (never sends)

Demo server must be running.

```bash
python -m taskwitness.interpret_goal --execute --headed --goal "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask me before sending any message."
```

Expected: stages may update when `change_stage` authority is true; drafts created; `send_message` deferred; Sent empty.

## Deterministic headed browser run (no model)

```bash
python -m taskwitness.browser_demo ^
  --role "AI Engineering" ^
  --status "Shortlisted" ^
  --target-stage "Interview Ready" ^
  --prepare-followups ^
  --headed
```

## Scenario notes

1. **Base** — AI Engineering shortlisted: prepare follow-up + set Interview Ready + ask before send.
2. **Variation** — Backend Engineering shortlisted: prepare follow-ups only.
3. **Failure/recovery** — later phases (ambiguous send). Approval UI is Phase 4.

## Cleanup/reset

```bash
python -m demo_env.seed --reset
```

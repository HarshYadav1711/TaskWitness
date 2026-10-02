# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It interprets recruiting goals, executes authorized work against synthetic business apps, and will independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 8 complete — assignment scenarios and acceptance harness.** Reproducible assessment scenarios (`base`, `variation`, `recovery`, `rejection`, `pause`) run through the operator UI in Validated Plan Demo Mode. Live LLM interpretation checks remain pending until credentials are used for a real pre-submission pass.

## Requirements

- Python 3.12+

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e ".[dev]"
python -m playwright install chromium
```

## Model configuration (live interpretation only)

Copy `.env.example` values into your environment (do not commit `.env`):

| Variable | Required for live NL? | Notes |
|---|---|---|
| `LLM_API_KEY` | Yes | Never commit a real key |
| `LLM_MODEL` | Yes | Provider model id |
| `LLM_BASE_URL` | No | Optional OpenAI-compatible base URL; empty → client default |

**Model required:** `python -m taskwitness.interpret_goal`, `python -m taskwitness.interpret_eval`
**Model not required:** `pytest`, `demo_env`, `taskwitness.browser_demo`, `taskwitness.control_demo`, `taskwitness.recovery_demo`, `taskwitness.verify_demo`, `taskwitness.operator_demo --demo-plan …` (validated-plan development mode)

## Synthetic environment

```bash
python -m demo_env.seed --reset
python -m demo_env
```

| Application | URL |
|---|---|
| TalentDesk | http://127.0.0.1:8000/talentdesk |
| TeamMail | http://127.0.0.1:8000/teammail |

## Phase 4 control demo (approval / progress)

Reset + start the demo apps, then:

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --headed
```

Interactive terminal approval for gated sends. Non-interactive options:

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --headed
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --reject-all --headed
```

Optional cooperative pause listener (workflow worker thread; type `p` / `r`):

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --console-control --headed
```

Control/approval/pause state is **in-memory** for the process. Effectful actions are journaled. Optional independent verification:

```bash
python -m taskwitness.control_demo --from-taskspec examples/base-plan.json --approve-all --verify --headed
```

## Durable journal + recovery (Phase 5)

Local assessment journal (not production persistence; not `demo_env` SQLite):

| Setting | Default |
|---|---|
| Path | `.taskwitness/journal.sqlite3` |
| Override | `TASKWITNESS_JOURNAL` |

Ambiguous-send recovery demo (arms the synthetic one-shot fault, then reconciles Sent):

```bash
python -m demo_env.seed --reset
python -m demo_env
python -m taskwitness.recovery_demo --from-taskspec examples/base-plan.json --reset-journal --headed
```

Expected: draft → approval (if authority false) → Send persists → acknowledgement interrupted → journal `UNKNOWN` → inspect Sent → `RECOVERED` without a second Send.

Optional: append independent verification + evidence after recovery:

```bash
python -m taskwitness.recovery_demo --from-taskspec examples/base-plan.json --reset-journal --verify --headed
```

## Operator console (Phase 7)

Prerequisite: synthetic apps running on port 8000.

```bash
python -m demo_env.seed --reset
python -m demo_env
```

Normal path (live interpretation — requires `LLM_API_KEY` + `LLM_MODEL`):

```bash
python -m taskwitness.operator_demo --headed
```

Open [http://127.0.0.1:8010/operator](http://127.0.0.1:8010/operator). Enter a plain-English goal and click **Run**.

**Validated Plan Demo Mode** (development only — not live NL interpretation):

```bash
python -m taskwitness.operator_demo --demo-plan examples/base-plan.json --headed
```

Use **Start validated plan** in the UI. The same workflow, authority gates, journal, recovery, and verification path run; the banner makes the mode obvious.

Limitations (intentional):

- one active operator run at a time;
- live UI/run registry is in-memory for the operator process (journal remains durable);
- page reload can reattach to the current in-process run; operator-server restart does not restore UI state.

Optional demo pacing: `--slow-mo 100`.

## Assessment acceptance (Phase 8)

Deterministic assignment scenarios (Validated Plan Demo Mode — not live NL):

```bash
python -m taskwitness.assessment_accept --scenario base
python -m taskwitness.assessment_accept --scenario variation
python -m taskwitness.assessment_accept --scenario recovery
python -m taskwitness.assessment_accept --scenario all
```

Headed rehearsal:

```bash
python -m taskwitness.assessment_accept --scenario base --headed --slow-mo 60
```

Optional live-model interpret check (skipped without credentials):

```bash
python -m taskwitness.assessment_accept --scenario base --live-model
```

See [docs/ASSESSMENT_MAP.md](docs/ASSESSMENT_MAP.md) for requirement → scenario mapping.

## Independent verification and evidence (Phase 6)

Execution completion ≠ goal verified. After a run finishes (and its browser session closes), verify independently:

```bash
python -m taskwitness.verify_demo --run-id <RUN_ID> --headed
```

Evidence is written under `evidence/<run_id>/` (generated runtime artifact; gitignored):

| File | Contents |
|---|---|
| `summary.md` | Human-readable VERIFIED / INCOMPLETE / FAILED / BLOCKED |
| `manifest.json` | Artifact list + SHA-256 (integrity, not signing) |
| `task_spec.json` | Immutable TaskSpec snapshot (authority unchanged) |
| `verification.json` | Postcondition checks + overall status |
| `journal.json` | This run’s journal export only |
| `progress.jsonl` | Optional; present when progress events were supplied |
| `screenshots/` | Final-state captures tied to checks |

Standalone post-run verification by `run_id` always remains available.

## Natural-language interpretation (Phase 3)

Interpret only (no browser):

```bash
python -m taskwitness.interpret_goal --goal "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask me before sending any message."
```

Optional execute (READY plans → Phase 4 workflow with approval gates):

```bash
python -m taskwitness.interpret_goal --execute --approve-all --goal "..."
```

## Deterministic browser demo (no model)

Drafts + authorized stages (no send unless TaskSpec + approval path):

```bash
python -m taskwitness.browser_demo ^
  --role "AI Engineering" ^
  --status "Shortlisted" ^
  --target-stage "Interview Ready" ^
  --prepare-followups ^
  --headed
```

## Tests

```bash
python -m pytest -q
```

## Documentation

- [Project context](docs/PROJECT_CONTEXT.md)
- [Rules](docs/RULES.md)
- [PRD](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Design](docs/DESIGN.md)
- [Phases](docs/PHASES.md)
- [Agent instructions](AGENTS.md)
- [Engineering note](ENGINEERING_NOTE.md)
- [Demo runbook](DEMO.md)

## Synthetic data

All candidates and emails are fictional. Addresses use `example.test`. No real people, companies, or outbound mail.

## Not yet implemented

- Live-provider pre-submission interpretation check (manual; credentials required)
- Final demo video / submission polish (Phase 10)
- Adversarial hardening sweep (Phase 9)

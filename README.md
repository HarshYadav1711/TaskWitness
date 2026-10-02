# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It interprets recruiting goals, executes authorized work against synthetic business apps, and will independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 4 complete — human control and authority.** Requested actions and authority remain separate. False-authority stage/send actions request human approval immediately before the side effect. Cooperative pause/resume and an in-memory progress stream are available. Control state is process-local (not durable). No final operator UI yet.

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
**Model not required:** `pytest`, `demo_env`, `taskwitness.browser_demo`, `taskwitness.control_demo` (deterministic TaskSpec JSON)

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

Control/approval/pause state is **in-memory only** for this process. There is no durable journal and no final web operator UI yet.

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

- Durable TaskWitness execution journal and ambiguous-outcome recovery
- Independent verification and evidence packs
- Final operator UI (Phase 7)

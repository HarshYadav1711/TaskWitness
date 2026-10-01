# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It interprets recruiting goals, executes authorized work against synthetic business apps, and will independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 3 complete — natural-language goal interpretation.** Plain-English goals become validated `TaskSpec` plans via an OpenAI-compatible model boundary, then local schema + policy checks. Deterministic Playwright workflow is unchanged. Messages are still never sent (deferred until Phase 4).

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
**Model not required:** `pytest`, `demo_env`, `taskwitness.browser_demo` (deterministic WorkflowConfig / TaskSpec JSON)

## Synthetic environment

```bash
python -m demo_env.seed --reset
python -m demo_env
```

| Application | URL |
|---|---|
| TalentDesk | http://127.0.0.1:8000/talentdesk |
| TeamMail | http://127.0.0.1:8000/teammail |

## Natural-language interpretation (Phase 3)

Interpret only (no browser):

```bash
python -m taskwitness.interpret_goal --goal "From candidates.csv, process shortlisted AI Engineering candidates in TalentDesk. Prepare an interview follow-up, move each matching candidate to Interview Ready, and ask me before sending any message."
```

Optional execute (READY plans only → existing Phase 2 workflow; never sends):

```bash
python -m taskwitness.interpret_goal --execute --goal "..."
```

Optional live fixture eval (no Playwright):

```bash
python -m taskwitness.interpret_eval
```

## Deterministic browser demo (no model)

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

- Authority gates, pause/resume runtime (approval UI)
- Durable TaskWitness execution journal and recovery
- Independent verification and evidence packs
- Operator UI

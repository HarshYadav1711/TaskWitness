# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It will interpret recruiting goals, execute authorized work against synthetic business apps, and independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 2 complete — deterministic browser execution.** TaskWitness operates TalentDesk and TeamMail through Playwright (Chromium). Follow-ups are saved as drafts only; autonomous send is deferred until the authority phase. No LLM yet.

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

## Synthetic environment

Reset:

```bash
python -m demo_env.seed --reset
```

Run TalentDesk + TeamMail:

```bash
python -m demo_env
```

| Application | URL |
|---|---|
| TalentDesk | http://127.0.0.1:8000/talentdesk |
| TeamMail | http://127.0.0.1:8000/teammail |

## Phase 2 browser demo

Prerequisite: demo environment running (above).

Headed (default — visible Chromium for demos):

```bash
python -m taskwitness.browser_demo ^
  --role "AI Engineering" ^
  --status "Shortlisted" ^
  --target-stage "Interview Ready" ^
  --prepare-followups ^
  --headed
```

Headless (tests/CI):

```bash
python -m taskwitness.browser_demo --headless --role "AI Engineering" --status "Shortlisted"
```

Optional `--slow-mo 150` adds Playwright presentation pacing for demos only (not used by correctness waits).

The workflow never sends mail. `send_message` from a TaskSpec is deferred.

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

- Natural-language goal interpretation
- Authority gates, pause/resume runtime
- Durable TaskWitness execution journal and recovery
- Independent verification and evidence packs
- Operator UI

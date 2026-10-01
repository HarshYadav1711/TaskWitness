# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It will interpret recruiting goals, execute authorized work against synthetic business apps, and independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 1 complete — synthetic business applications.** TalentDesk and TeamMail run locally with durable SQLite state, seed/reset, and schema contracts from Phase 0. TaskWitness browser automation is not implemented yet.

## Requirements

- Python 3.12+

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e ".[dev]"
```

## Synthetic environment

Reset (reloads `data/candidates.csv`, clears TeamMail):

```bash
python -m demo_env.seed --reset
```

Run TalentDesk + TeamMail (one FastAPI process):

```bash
python -m demo_env
```

| Application | URL |
|---|---|
| TalentDesk | http://127.0.0.1:8000/talentdesk |
| TeamMail | http://127.0.0.1:8000/teammail |

TeamMail accepts only `@example.test` recipients and never delivers external mail.

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

- Playwright browser execution by TaskWitness
- Natural-language goal interpretation
- Authority gates, pause/resume runtime
- Durable TaskWitness execution journal and recovery
- Independent verification and evidence packs
- Operator UI
- Assignment scenario harness beyond demo-env and schema tests

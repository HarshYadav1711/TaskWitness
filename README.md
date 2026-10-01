# TaskWitness

Evidence-first, human-controlled computer operator for a HulChul AI Engineering internship assessment. It will interpret recruiting goals, execute authorized work against synthetic business apps, and independently verify outcomes.

## Assessment context

Built as a time-boxed prototype demonstrating useful multi-step computer operation with human authority, failure recovery, and evidence—not a general-purpose computer-use framework.

## Core philosophy

AI interprets intent. Deterministic software performs side effects. Independent verification determines completion.

## Current status

**Phase 0 — foundation and contracts.** Documentation, typed `TaskSpec`, synthetic candidate fixtures, and schema tests. No application operator yet.

## Requirements

- Python 3.12+

## Setup and tests

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e ".[dev]"
python -m pytest -q
```

If editable install is unavailable, `pip install "pydantic>=2.7,<3" "pytest>=8.2,<9"` is enough for Phase 0; pytest uses `pythonpath = ["."]`.

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

- TalentDesk / TeamMail synthetic applications
- Playwright browser execution
- Natural-language goal interpretation
- Authority gates, pause/resume runtime
- Durable journal and recovery
- Independent verification and evidence packs
- Operator UI
- Assignment scenario harness beyond schema tests

# TaskWitness — Architecture

## Architecture goals

- Separate interpretation from execution and verification.
- Keep side effects deterministic and authority-gated.
- Make failure and recovery inspectable.
- Stay small enough to own and explain under a time-box.

## System boundaries

**In scope (eventually):** local operator control surface, goal interpreter → `TaskSpec`, deterministic executor against synthetic TalentDesk/TeamMail, durable journal, independent verification, evidence.

**Out of scope:** general computer-use agents, production integrations, distributed infra, multi-agent orchestration frameworks.

## High-level pipeline

```
Plain-English Goal
        |
        v
Goal Interpreter
        |
        v
Validated TaskSpec
        |
        v
Authority Check
        |
        v
Deterministic Executor
        |
        v
Target Applications
        |
        v
Independent Verification
        |
        v
Evidence
```

Operating loop: **Understand → Execute → Verify**.

## Responsibility boundaries

| Concern | Owner |
|---|---|
| Intent from natural language | Goal Interpreter (LLM-assisted) |
| Schema validity | `TaskSpec` / Pydantic boundary |
| Whether an action may run autonomously | Authority Check |
| App side effects | Deterministic Executor |
| Application truth | TalentDesk / TeamMail state |
| Completion decision | Independent Verification |
| Operator visibility / pause / approve | Operator UI + control API |

## Trust boundaries

1. **LLM output is untrusted.** It may propose intent only. It does not authorize, execute arbitrarily, or prove success.
2. **`TaskSpec` is the execution contract.** Invalid or contradictory plans stop before side effects.
3. **Authority is enforced in software**, not by prompt wording alone.
4. **Verification reads application state**, independent of executor return values.

## Planned components

| Component | Role | Status |
|---|---|---|
| Domain schemas (`TaskSpec`, authority, run state) | Typed contract | **Implemented (Phase 0)** |
| Synthetic TalentDesk / TeamMail | Controlled apps | **Implemented (Phase 1)** |
| Playwright executor | Visible browser ops | Not implemented |
| Goal interpreter | NL → `TaskSpec` | Not implemented |
| Authority / pause controls | Human gates | Not implemented |
| SQLite TaskWitness journal | Durable effect history | Not implemented |
| Verification + evidence | Postconditions + artifacts | Not implemented |
| FastAPI + HTML/CSS/JS operator UI | Local operator surface | Not implemented |

### Synthetic applications (Phase 1)

- One FastAPI process hosts two distinct surfaces: `/talentdesk` and `/teammail`.
- One process was chosen to keep the assessment local and simple; the apps remain separate products with separate responsibilities and UI chrome.
- Persistence: SQLite via Python `sqlite3` at `demo_env/demo_env.sqlite3` (override with `DEMO_ENV_DB`).
- Demo app state is **not** the future TaskWitness execution journal. Journals belong to later phases and must stay conceptually separate.
- TeamMail stores an optional unique `operation_id` for later duplicate-safe recovery. A test-only one-shot flag `fail_after_send_commit_once` can interrupt acknowledgement after a successful local send commit; disabled by default.
- FastAPI here serves only the synthetic apps—not a TaskWitness operator/control API.

## Technology decisions

**Python 3.12** — one primary language for automation and typed AI-adjacent workflows; strong fit for Playwright and assessment ownership.

**Pydantic v2** — model/planner output is untrusted; strict schemas form the boundary before execution.

**Playwright (planned)** — visible application execution is required; direct automation keeps selectors, actions, and failures explicit; avoids opaque autonomous browser-agent frameworks.

**SQLite** — used now for synthetic TalentDesk/TeamMail state; planned separately later for the TaskWitness execution journal. No extra database infrastructure.

**FastAPI** — hosts the Phase 1 synthetic apps today; planned later for the local operator/control API. Still no distributed service architecture.

**HTML/CSS/JS** — authored server-rendered pages for TalentDesk/TeamMail; React would add assessment overhead without proportional value. Operator UI remains later.

**Uvicorn** — local ASGI server for the demo environment.

**LLM (planned)** — interpretation of plain-English intent only; not source of execution truth, authority, or completion truth.

## Data/state flow

Goal text → interpreter → validated `TaskSpec` → executor steps → journalled effects → verification against apps → evidence pack → terminal run state (`completed` / `partial` / `failed`).

## Authority enforcement

Requested `actions` and `authority` are independent fields. An action may appear in the plan while autonomous authority is false; execution must enter `awaiting_approval` before that side effect. Schema validation does not collapse this distinction.

## Execution philosophy

Deterministic code performs side effects. The executor never invents capabilities outside the validated plan. Visible UI operation is required for demonstrated browser work; private APIs must not silently fake that demonstration.

## Verification philosophy

Success requires defined postconditions. Function return without exception is insufficient. Ambiguous outcomes require state inspection before any retry.

## Reliability philosophy

Journal effects. Prefer inspect-then-continue over blind retry. Suppress duplicate side effects. Make recovery an explicit run state.

## Known intentional constraints

- Synthetic apps and data only.
- Single-operator local prototype.
- No general computer-use capability surface.
- Time-boxed scope; phases gate delivery.

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
| Playwright executor | Visible browser ops | **Implemented (Phase 2)** |
| Goal interpreter | NL → `TaskSpec` | **Implemented (Phase 3)** |
| Authority / pause controls | Human gates | **Implemented (Phase 4)** |
| SQLite TaskWitness journal | Durable effect history | **Implemented (Phase 5)** |
| Verification + evidence | Postconditions + artifacts | **Implemented (Phase 6)** |
| Operator console | Local FastAPI + HTML/CSS/JS | **Implemented (Phase 7)** |

### Synthetic applications (Phase 1)

- One FastAPI process hosts two distinct surfaces: `/talentdesk` and `/teammail`.
- One process was chosen to keep the assessment local and simple; the apps remain separate products with separate responsibilities and UI chrome.
- Persistence: SQLite via Python `sqlite3` at `demo_env/demo_env.sqlite3` (override with `DEMO_ENV_DB`).
- Demo app state is **not** the future TaskWitness execution journal. Journals belong to later phases and must stay conceptually separate.
- TeamMail stores an optional unique `operation_id` for later duplicate-safe recovery. A test-only one-shot flag `fail_after_send_commit_once` can interrupt acknowledgement after a successful local send commit; disabled by default.
- FastAPI here serves only the synthetic apps—not a TaskWitness operator/control API.

### Deterministic browser execution (Phase 2)

- Playwright Chromium operates TalentDesk/TeamMail through visible UI controls only.
- Browser adapters (`TalentDeskBrowser`, `TeamMailBrowser`) expose domain operations; Playwright stays inside that boundary.
- Candidate selection is read from `data/candidates.csv` via `candidate_source` — never from `demo_env` SQLite.
- TaskWitness production browser/workflow code must not import `demo_env.db` or open `demo_env.sqlite3` to mutate or decide business state.
- Immediate post-action UI confirmation (e.g. stage notice, draft saved, sent detail) is allowed for reliable automation. That is **not** the future independent verification/evidence subsystem.
- Phase 2 introduced draft preparation. Phase 4 adds authority-gated send through the visible TeamMail UI.

### Natural-language interpretation (Phase 3)

- Narrow OpenAI-compatible client (`LLM_BASE_URL` optional, `LLM_API_KEY` + `LLM_MODEL` required for live interpretation).
- Model output is **untrusted**. It never calls Playwright, invents selectors, or proves success.
- Flow: goal → model JSON → local envelope parse → `TaskSpec.model_validate` → deterministic environment policy → `InterpretationResult`.
- Only READY `TaskSpec` values may hand off to the control-aware workflow (`config_from_taskspec` → `RecruitingWorkflow`).
- Ambiguous goals return `needs_clarification` (no execution). Policy rejects unsafe sources/roles/stages without silent repair.
- Phase 3 produces intent only. Phase 4 enforces authority gates; the model never grants approval.

### Human control and authority (Phase 4)

- **Requested actions ≠ autonomous permission.** `actions` may include `send_message` / `set_stage` while the matching `authority` flag is false; execution must obtain human approval immediately before that side effect.
- **ApprovalProvider** boundary (`request_approval` → `APPROVED` | `REJECTED`). Implementations: `AlwaysApprove` / `AlwaysReject` / `ScriptedApprovalProvider` (tests), `TerminalApprovalProvider` (dev stdin). `RecruitingWorkflow` never calls `input()` directly.
- Approvals are **action-scoped and one-time**. Approving CAND-001's send does not authorize CAND-002 or rewrite `TaskSpec.authority`.
- **RunControl** provides cooperative pause/resume via standard library synchronization. Pause stops at safe checkpoints (before next candidate / stage / draft / send)—not mid-Playwright click.
- Precedence: `awaiting_approval` is its own halt; a pause requested during approval remains pending and is honored at the next checkpoint after approval resolves.
- **Progress events** are an in-memory sink/callback stream (timestamp, run state, optional candidate/action, message) for tests and the future Phase 7 UI. Not durable event sourcing.
- **TeamMail send** is a browser domain operation (`send_draft`) through the visible Send control. The draft's `operation_id` is preserved from draft → sent.
- Control/approval/progress state remains in-memory for operator interaction. Durable effect history lives in the TaskWitness journal (Phase 5).
- Rejection leaves completed work intact and yields `PARTIAL` when requested work remains incomplete—not a false `FAILED`.

### Durable journal and recovery (Phase 5)

- Local SQLite journal at `.taskwitness/journal.sqlite3` (override `TASKWITNESS_JOURNAL`). Completely separate from `demo_env` persistence.
- **Write-ahead:** plan action → mark `IN_PROGRESS` (commit) → only then invoke browser mutation.
- **action_key** identifies the logical journaled effect within a run (stable hash of run_id + action_type + candidate + normalized payload). **operation_id** remains the TeamMail business identity used for Sent reconciliation.
- Outcomes distinguish known success/failure from **UNKNOWN** (acknowledgement inconclusive). UNKNOWN is never treated as permission to blindly resend.
- Recovery for UNKNOWN send: inspect visible Sent by `operation_id`. Exactly one match → `RECOVERED` (no retry). Zero conclusive matches → one controlled same-operation retry. Multiple matches or inspection unavailable → `BLOCKED`.
- Recovery verification asks only whether this uncertain side effect already happened. Whole-goal completion verification is Phase 6 (independent of recovery).
- `RunState.recovering` is used during target-state reconciliation. A recovered send counts as completed work for run completion semantics.
- Approval precedes attempted-action journaling: reject → `REJECTED` with `attempt_count=0` (never `IN_PROGRESS`).

### Independent verification and evidence (Phase 6)

- After execution finishes, a **fresh browser session** inspects TalentDesk and TeamMail final state. Executor `success` booleans, journal `SUCCEEDED`/`RECOVERED`, and the LLM are not proof of business completion.
- Expected candidates are re-derived from `TaskSpec.source_file` + role/status via `candidate_source` — not from `BrowserRunResult.processed_candidates`.
- Deterministic postconditions cover requested actions: stage equals target, follow-up artifact (draft or sent) by `operation_id`, exactly-one Sent when send was authorized/completed, send-absent safety when send was rejected or not requested.
- Overall statuses: `passed` (verified complete), `incomplete` (safe but unfinished, e.g. rejection), `failed` (contradictory state), `blocked` (inspection unavailable). Workflow run state is not rewritten by verification.
- **EvidenceWriter** is separate from **GoalVerifier**: verification determines truth; writer emits `summary.md`, `manifest.json` (SHA-256 per artifact, not self-hashed), `task_spec.json`, `verification.json`, `journal.json`, optional `progress.jsonl`, and scoped screenshots under gitignored `evidence/<run_id>/`.
- Hashes provide package integrity checking, not cryptographic identity/signing. Paths are sanitized; run_id may not escape the evidence root.
- Recovery reconciles uncertain side effects; final verification re-proves the business postcondition independently.

### Operator console (Phase 7)

- Separate process from synthetic apps: apps on `:8000`, operator on `:8010` (`python -m taskwitness.operator_demo`).
- **In-memory ActiveRun registry** coordinates live UI state (progress, pending approval, verification summary). Durable effect history remains the TaskWitness journal.
- **One active run at a time** for this local prototype. A second start is rejected cleanly until the current run is terminal.
- Worker thread runs: interpret (or validated-plan demo) → `RecruitingWorkflow` with `RunControl` + `WebApprovalProvider` + progress sink + journal → close execution browser → fresh verification → evidence.
- UI polls `GET /api/runs/{id}` ~500ms (chosen over WebSockets for local simplicity). Approval resolve is server-enforced exactly once.
- Normal UI path is plain-English interpretation. **Validated Plan Demo Mode** (`--demo-plan`) is an explicit development banner path — not silent NL bypass; still uses the same authority/approval/verification pipeline.
- Live UI state does not survive operator-server restart; journal durability is separate.

### Assessment acceptance harness (Phase 8)

- `taskwitness.assessment_accept` orchestrates isolated demo_env + operator processes, drives the operator UI (Validated Plan Demo Mode), and asserts assignment scenarios: base, variation, recovery, rejection, pause.
- Scenario isolation resets synthetic DB + journal per run. Assertions may inspect synthetic DB for outcomes; business mutations still occur only through Playwright.
- Optional `--live-model` interprets goals when credentials exist; otherwise reports SKIPPED. Automated pytest never requires a live model.

## Technology decisions

**Python 3.12** — one primary language for automation and typed AI-adjacent workflows; strong fit for Playwright and assessment ownership.

**Pydantic v2** — model/planner output is untrusted; strict schemas form the boundary before execution. Provider structured output does not replace local validation.

**Playwright** — visible application execution; direct automation keeps selectors, actions, and failures explicit; avoids opaque autonomous browser-agent frameworks.

**openai (official client)** — minimal OpenAI-compatible adapter for intent interpretation only. No LangChain/LangGraph/agent frameworks.

**SQLite** — used for synthetic TalentDesk/TeamMail state; planned separately later for the TaskWitness execution journal. No extra database infrastructure.

**FastAPI** — hosts the synthetic apps and the TaskWitness operator API (separate processes/ports). Still no distributed service architecture.

**HTML/CSS/JS** — authored pages for TalentDesk/TeamMail and the operator console. No React/Next/build toolchain.

**Uvicorn** — local ASGI server for the demo environment.

**LLM** — interpretation of plain-English intent only; not source of execution truth, authority, or completion truth.

## Data/state flow

Goal text → interpreter → validated `TaskSpec` → executor steps → journalled effects → verification against apps → evidence pack → terminal run state (`completed` / `partial` / `failed`).

## Authority enforcement

Requested `actions` and `authority` are independent fields. An action may appear in the plan while autonomous authority is false; execution must enter `awaiting_approval` before that side effect. Schema validation does not collapse this distinction.

## Execution philosophy

Deterministic code performs side effects. The executor never invents capabilities outside the validated plan. Visible UI operation is required for demonstrated browser work; private APIs must not silently fake that demonstration.

## Verification philosophy

Success requires defined postconditions inspected against target application state in a fresh verification pass. Function return without exception, executor success flags, and journal SUCCEEDED/RECOVERED are insufficient alone. Ambiguous outcomes require state inspection before any retry. Rejected requested actions are safe but incomplete — not verified complete.

## Reliability philosophy

Journal effects. Prefer inspect-then-continue over blind retry. Suppress duplicate side effects. Make recovery an explicit run state.

## Known intentional constraints

- Synthetic apps and data only.
- Single-operator local prototype.
- No general computer-use capability surface.
- Time-boxed scope; phases gate delivery.

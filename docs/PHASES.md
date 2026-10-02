# TaskWitness — Phases

Implement only the phase explicitly requested. Do not advance automatically.

---

## Phase 0 — Context, requirements and task contract

**Objective:** Lock product context, rules, architecture, design principles, phase plan, typed `TaskSpec`, synthetic fixtures, and schema tests.

**Planned work:** Governance docs; `taskwitness.schemas`; `data/candidates.csv`; example plans; pytest coverage; minimal `pyproject.toml`.

**Allowed changes:** Documentation and domain contract files listed for Phase 0.

**Forbidden changes:** Apps, browser automation, FastAPI, UI, journal, LLM client, verification engine, recovery engine.

**Acceptance criteria:** Required docs exist; schemas reject invalid plans; examples validate; tests pass.

**Required automated tests:** `tests/test_schemas.py` covering validity, contradiction rejection, authority separation, `RunState`.

**Required manual checks:** Example JSON validates through `TaskSpec`; no later-phase code leaked; synthetic-data policy held.

**Expected commit message:** `chore: lock assessment scope and task contract`

---

## Phase 1 — Synthetic business applications

**Status:** Complete

**Objective:** Provide TalentDesk, TeamMail, and supporting fixtures as a controlled recruiting test environment.

**Planned work:** Authored synthetic HTML/JS apps; local serving; seed data aligned with `candidates.csv`; documented test-only failure mode hook for later phases.

**Allowed changes:** Synthetic app assets and minimal local serving needed to run them.

**Forbidden changes:** Playwright executor, LLM interpreter, journal, operator UI productization, real email/ATS.

**Acceptance criteria:** Apps open locally; candidates visible; stage and draft/send paths usable manually; failure-mode hook documented.

**Required automated tests:** App/data integrity checks appropriate to the phase (no full browser E2E yet unless explicitly scoped).

**Required manual checks:** Manual walkthrough of TalentDesk stage change and TeamMail draft/send in the synthetic environment.

**Expected commit message:** `feat: add synthetic recruiting test environment`

---

## Phase 2 — Deterministic browser execution

**Status:** Complete

**Objective:** Execute recruiting workflow steps through Playwright against the synthetic apps.

**Planned work:** Deterministic operators for inspect/update stage and prepare/send mail; visible interaction; no LLM in the loop yet (drive from validated plans/fixtures).

**Allowed changes:** Playwright-based executor modules and config required for local browser runs.

**Forbidden changes:** Autonomous browser-agent frameworks; private-API shortcuts that fake demonstrated UI work; goal interpreter.

**Acceptance criteria:** Base plan steps run visibly against TalentDesk/TeamMail from a validated `TaskSpec`.

**Required automated tests:** Focused executor tests that assert intended UI-driven outcomes in the controlled environment.

**Required manual checks:** Watch a run perform real browser interactions.

**Expected commit message:** `feat: execute recruiting workflow through playwright`

---

## Phase 3 — Natural-language goal interpretation

**Status:** Complete

**Objective:** Parse plain-English goals into validated `TaskSpec` plans.

**Planned work:** Configurable OpenAI-compatible adapter; prompt constrained to schema fields; reject invalid output at the Pydantic boundary.

**Allowed changes:** Interpreter module and model config via environment variables.

**Forbidden changes:** LLM-driven arbitrary browser commands; treating model text as success proof; authority bypass.

**Acceptance criteria:** Base and variation goals produce valid `TaskSpec`s without source changes between runs.

**Required automated tests:** Fixture goals → schema validation; malformed model output rejected.

**Required manual checks:** Run both scenario phrasings end-to-end into plans.

**Expected commit message:** `feat: parse goals into validated task plans`

---

## Phase 4 — Human control and authority

**Status:** Complete

**Objective:** Enforce authority gates and execution controls (pause / approval).

**Planned work:** `awaiting_approval` transitions; pause/resume; deny → visible partial outcomes.

**Allowed changes:** Control-plane semantics and APIs needed for pause and approval.

**Forbidden changes:** Softening authority into prompt-only checks; auto-approving gated actions.

**Acceptance criteria:** `send_message` with `authority.send_message=false` pauses for approval; reject/approve behaviors correct; pause works.

**Required automated tests:** Authority gate and pause/resume state transitions.

**Required manual checks:** Approve and reject paths in a live run.

**Expected commit message:** `feat: add authority gates and execution controls`

---

## Phase 5 — Durable journal and failure recovery

**Status:** Complete

**Objective:** Persist effect history and safely recover from ambiguous outcomes.

**Planned work:** SQLite journal; ambiguous-send recovery path (inspect before retry; suppress duplicates).

**Allowed changes:** Journal schema/storage and recovery logic for documented failure modes.

**Forbidden changes:** Blind retries; duplicate sends; changing verification ownership to the LLM.

**Acceptance criteria:** Interrupted send recovers without duplicate message; recovery recorded.

**Required automated tests:** Ambiguous-send recovery; duplicate suppression.

**Required manual checks:** Demo the failure mode and recovered journal/state.

**Expected commit message:** `feat: add durable journal and safe recovery`

---

## Phase 6 — Independent verification and evidence

**Status:** Complete

**Objective:** Verify outcomes via postconditions and generate run evidence.

**Planned work:** Postcondition checks against app state/artifacts; evidence pack; terminal states including `partial`.

**Allowed changes:** Verification and evidence modules.

**Forbidden changes:** Declaring success from executor return alone; fabricating metrics.

**Acceptance criteria:** Completion requires postconditions; evidence reflects resulting state; incomplete work can be `PARTIAL`.

**Required automated tests:** Pass/fail postconditions; evidence contents for fixture runs.

**Required manual checks:** Inspect evidence for base, variation, and recovery demos.

**Expected commit message:** `feat: verify outcomes and generate run evidence`

---

## Phase 7 — Operator UI

**Status:** Complete

**Objective:** Add a calm operator control interface aligned with `DESIGN.md`.

**Planned work:** FastAPI + HTML/CSS/JS surface; goal input; trace; pause; approval; evidence/status.

**Allowed changes:** Local UI and control API wiring to existing backend capabilities.

**Forbidden changes:** React/Next rewrite; decorative AI SaaS chrome; chat-first redesign.

**Acceptance criteria:** Operator can run, watch trace, pause, approve/reject, and see verification/evidence status.

**Required automated tests:** API/control smoke tests as appropriate; no UI fashion tests.

**Required manual checks:** Full UI walkthrough against design rules.

**Expected commit message:** `feat: add operator control interface`

---

## Phase 8 — Assignment scenarios and tests

**Objective:** Cover assignment execution scenarios as automated and documented checks.

**Planned work:** Base, variation, and failure/recovery scenario harnesses.

**Allowed changes:** Scenario fixtures and tests; thin glue only.

**Forbidden changes:** New product features unrelated to scenario coverage.

**Acceptance criteria:** Assignment scenarios runnable and asserted.

**Required automated tests:** Scenario suite for the three demonstration paths.

**Required manual checks:** Cross-check demo runbook against suite expectations.

**Expected commit message:** `test: cover assignment execution scenarios`

---

## Phase 9 — Hardening and adversarial review

**Objective:** Harden against unsafe and ambiguous execution paths.

**Planned work:** Adversarial cases (malformed plans, authority edge cases, duplicate-risk paths); fix genuine gaps.

**Allowed changes:** Defensive checks and tests within existing architecture.

**Forbidden changes:** Scope expansion disguised as hardening.

**Acceptance criteria:** Unsafe/ambiguous paths fail closed or recover per rules; tests document findings.

**Required automated tests:** Adversarial suite.

**Required manual checks:** Review residual risks in engineering note.

**Expected commit message:** `test: harden operator against unsafe and ambiguous execution`

---

## Phase 10 — Documentation, demo and submission

**Objective:** Finalize assessment submission package.

**Planned work:** README run instructions; finalize `ENGINEERING_NOTE.md` and `DEMO.md`; demo video prep; source package check.

**Allowed changes:** Docs and submission packaging only (plus trivial fix-ups discovered during finalization).

**Forbidden changes:** New features.

**Acceptance criteria:** Setup/run docs accurate; demo runbook complete; engineering note honest; submission artifacts ready.

**Required automated tests:** Full relevant suite green.

**Required manual checks:** Dry-run all three demo scenarios; verify claims match reality.

**Expected commit message:** `docs: finalize assessment submission package`

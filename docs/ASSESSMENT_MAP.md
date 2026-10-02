# TaskWitness — Assessment Requirement Map

Short mapping of HulChul assignment requirements to implemented behavior and Phase 8 scenarios.

Mode note: deterministic acceptance uses **Validated Plan Demo Mode**. That proves the operator/control/recovery/verification path. It does **not** claim live LLM interpretation quality. Live-provider checks remain a pre-submission manual requirement.

---

## Working execution

**Implemented by:** Playwright TalentDesk/TeamMail adapters + `RecruitingWorkflow` + operator console.

**Acceptance scenario:** `BASE`

**Evidence:** Operator UI run; headed Chromium operates apps; stages/drafts/sends; independent verification; evidence package.

---

## Adaptability

**Implemented by:** Validated `TaskSpec` + same deterministic workflow (no source edits between goals). Live path: `GoalInterpreter` → `TaskSpec` when credentials configured.

**Acceptance scenario:** `VARIATION`

**Evidence:** Backend Engineering shortlisted candidates; prepare_followup only; no stage change; no send; verification VERIFIED.

---

## Recovery

**Implemented by:** Write-ahead journal; ambiguous send → `UNKNOWN`; Sent UI inspect by stable `operation_id`; `RECOVERED` without blind retry.

**Acceptance scenario:** `RECOVERY`

**Evidence:** One-shot post-commit fault; attempt_count=1; exactly one Sent match; final verification VERIFIED; evidence journal includes recovered action.

---

## Verified completion

**Implemented by:** Fresh-browser `GoalVerifier` + `EvidenceWriter` after execution.

**Acceptance scenarios:** `BASE`, `VARIATION`, `RECOVERY` (and `REJECTION` for incomplete truthfulness).

**Evidence:** `verification.json`, `summary.md`, `manifest.json` SHA-256 integrity; `verified_complete` only when required postconditions pass.

---

## Human control

**Implemented by:** `authority` separate from `actions`; `WebApprovalProvider`; `RunControl` pause/resume; progress events in operator UI.

**Acceptance scenarios:** `BASE` (approval before send), `REJECTION`, `PAUSE`

**Evidence:** Approval dialog before Send; rejected send not executed / PARTIAL + INCOMPLETE; pause reaches RunControl then resume continues.

---

## Source / setup

**Implemented by:** Local Python project, synthetic `demo_env`, `data/candidates.csv`, documented README/DEMO.

**Acceptance:** `python -m taskwitness.assessment_accept --scenario …`

**Live NL setup:** `LLM_API_KEY` + `LLM_MODEL` (optional `LLM_BASE_URL`). Pending live pre-submission check if not yet performed.

---

## Demo video

**Status:** Pending Phase 10

Harness supports headed rehearsal (`--headed`) for base / variation / recovery without producing the final video in Phase 8.

---

## Engineering note

**Status:** Maintained alongside implementation; final personal/AI attribution sections Pending Phase 10 / submission polish.

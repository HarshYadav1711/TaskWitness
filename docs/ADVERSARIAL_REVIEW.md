# TaskWitness — Adversarial Review (Phase 9)

Focused fail-closed review of safety/reliability boundaries.
Not a professional security audit. Fixes only where a concrete defect was demonstrated.

---

## Input / schema

Case:
Unknown TaskSpec fields, unsupported ActionType, duplicate actions, target_stage contradictions, blank fields, unexpected authority fields, nested/executable extras, malformed model JSON.

Expected:
Nothing invalid reaches deterministic execution.

Evidence:
`tests/test_schemas.py`, `tests/test_interpretation.py`, `tests/test_hardening.py` (schema / hostile NL cases)

Result:
PASS

---

## Source path

Case:
`../secret.csv`, `../../.env`, `data/../.env`, absolute OS paths, `file://`, `https://`, `data:…`

Expected:
Rejected before file access/execution. Only approved `data/candidates.csv` may execute.

Evidence:
`tests/test_hardening.py::test_hostile_source_paths_rejected_by_policy`, `test_config_from_taskspec_rejects_hostile_source`, `test_workflow_rejects_hostile_source_before_load`

Result:
PASS (after fix)

Fix:
Execution entry (`config_from_taskspec` + `RecruitingWorkflow.run`) now calls `resolve_execution_source`, which allows only paths that resolve to the approved CSV. Absolute paths are permitted only when they resolve to that same file (test convenience). Traversal/`://`/`file:` rejected.

---

## Hostile natural-language goals

Case:
Prompt-injection style goals with FakeModelClient returning executable fields, unsupported actions, or `.env` source.

Expected:
Unsupported/hostile output never becomes an executable TaskSpec.

Evidence:
`tests/test_hardening.py::test_hostile_nl_goals_never_become_executable_taskspec`, `test_excessively_malformed_model_json_rejected`

Result:
PASS

---

## Authority bypass

Case:
`set_stage`/`send_message` with false authority and no approval; CLI/config cannot upgrade authority; approval for one candidate/action cannot authorize another.

Expected:
No mutation/send without matching approval; TaskSpec.authority unchanged.

Evidence:
`tests/test_control.py`, `tests/test_hardening.py` authority cases

Result:
PASS

---

## Approval replay / race

Case:
Double resolve; approve-then-reject; wrong id; stale id after next pending; concurrent dual resolve.

Expected:
Exactly one valid resolution; no second side effect.

Evidence:
`tests/test_operator.py::test_web_approval_resolves_once`, `tests/test_hardening.py::test_concurrent_approval_resolve_exactly_once`, stale/wrong-id cases

Result:
PASS (after fix)

Fix:
`WebApprovalProvider.resolve` now adds the approval id to `_resolved_ids` immediately under the condition lock, closing a race where two concurrent `resolve()` calls could both succeed before the waiter woke.

---

## Pause edges

Case:
Duplicate pause/resume; pause during approval then honor at next checkpoint; pause after terminal rejected.

Expected:
Documented cooperative-pause semantics; terminal pause rejected.

Evidence:
`tests/test_hardening.py` pause cases, `tests/test_control.py` pause/resume

Result:
PASS

---

## One active run

Case:
Near-simultaneous `POST /api/runs`; second start while first active.

Expected:
At most one active run; race does not create two workers.

Evidence:
`tests/test_operator.py::test_one_active_run_limit`, `tests/test_hardening.py::test_near_simultaneous_start_run_only_one_active`

Result:
PASS

---

## Candidate identity mismatch

Case:
CSV id matches; visible email/role/status does not.

Expected:
Candidate blocked; no stage/send for that candidate; no false VERIFIED from that path.

Evidence:
`tests/test_hardening.py::test_identity_mismatch_blocks_stage_and_send`

Result:
PASS

---

## Target unavailable

Case:
Clear TalentDesk failure before stage change; TeamMail unavailable during final verification.

Expected:
No false UNKNOWN for clear pre-effect failure; verification BLOCKED / `verified_complete=false` when target cannot be inspected.

Evidence:
`tests/test_hardening.py::test_clear_target_failure_before_effect_is_not_unknown`, `test_verification_blocked_when_target_disappears`

Result:
PASS

---

## Ambiguous send

Case:
One Sent match → RECOVERED, attempt_count==1, no retry.
Zero matches → one controlled retry; second ambiguity → BLOCKED.
Multiple matches → BLOCKED, no resend.
Inspection unavailable → BLOCKED (duplication risk).
Missing `operation_id` → BLOCKED, no blind resend.

Evidence:
`tests/test_journal.py`, `tests/test_hardening.py` ambiguous-send / missing-operation_id cases

Result:
PASS

---

## Journal transitions / reopen

Case:
SUCCEEDED→IN_PROGRESS, RECOVERED→UNKNOWN, REJECTED→IN_PROGRESS, BLOCKED→SUCCEEDED; reopen SUCCEEDED and refuse re-execution.

Expected:
Illegal transitions rejected; terminal actions not re-executed.

Evidence:
`tests/test_hardening.py` journal transition / reopen cases

Result:
PASS

---

## Action key / operation id

Case:
Same logical follow-up in same run → same identity; different candidate → different identity. `action_key` includes `run_id` (no cross-run dedupe claim).

Evidence:
`tests/test_hardening.py::test_action_key_and_operation_id_identity_rules`, `tests/test_journal.py`

Result:
PASS

---

## Verification false positives / skip / unintended send

Case:
Executor success with wrong stage; journal SUCCEEDED/RECOVERED with Sent count 0; Sent count >1; missing expected candidate postconditions; unintended Sent on prepare-only variation.

Expected:
FAILED / not VERIFIED; expected candidates derived from CSV, not executor processed list.

Evidence:
`tests/test_verification.py`, `tests/test_hardening.py` verification attack cases

Result:
PASS

---

## Evidence

Case:
Path-traversal run ids; alter artifact after package write; synthetic `LLM_API_KEY=TEST_SECRET_MUST_NOT_APPEAR` in environment during evidence generation.

Expected:
Unsafe ids rejected; hash mismatch detected; sentinel value absent from package. Manifest SHA-256 is integrity checking, not signing.

Evidence:
`tests/test_hardening.py` evidence cases, `tests/test_verification.py::test_evidence_path_traversal_rejected`

Result:
PASS

---

## Operator API / goal length / model errors

Case:
Hidden controls in POST body; empty/whitespace/over-limit goals; missing model config; provider error containing API key; malformed provider JSON.

Expected:
Extras rejected (422); over-limit rejected before model; MODEL_ERROR without browser workflow; key redacted; no execution from malformed output.

Evidence:
`tests/test_hardening.py` operator/model cases, `tests/test_operator.py`, `tests/test_interpretation.py`

Result:
PASS

---

## Frontend authority / refresh / XSS

Case:
Crafted approval without matching pending / replay after terminal; active-run snapshot after “reload”; operator.js dynamic strings.

Expected:
Approval rejected; snapshot reconstructs run/trace/pending; user/model strings via `textContent` (innerHTML only clears to empty).

Evidence:
`tests/test_hardening.py` frontend/API/XSS static cases

Result:
PASS

---

## External delivery

Case:
`person@gmail.com`, `person@outlook.com`

Expected:
TeamMail rejects non-`@example.test` recipients.

Evidence:
`tests/test_hardening.py::test_external_email_domains_rejected`, `tests/test_demo_env.py`

Result:
PASS

---

## Process cleanup / artifact hygiene

Case:
`.gitignore` covers journal/demo DB/evidence/`.env`; assessment harness stops uvicorn/browser per scenario.

Expected:
Runtime artifacts not stageable by default; processes cleaned after scenarios.

Evidence:
`tests/test_hardening.py::test_gitignore_covers_runtime_artifacts`; Phase 8 harness `ProcessBundle.stop`

Result:
PASS (no new process-management framework; no cleanup defect requiring a code change observed in Phase 9)

---

## Static dangerous-pattern review

Case:
Search production `taskwitness/` and `demo_env/` for `eval(`, `exec(`, `shell=True`, `os.system`, `pickle.loads`; operator.js `innerHTML` assignments.

Expected:
No unnecessary dangerous primitives; `innerHTML` only used to clear containers.

Evidence:
`tests/test_hardening.py::test_static_dangerous_pattern_review`, `test_operator_js_uses_textcontent_for_dynamic_strings`

Result:
PASS — no production hits requiring change. `open()` usages are for controlled local paths (CSV, evidence files), not model-supplied paths after the source gate.

---

## Residual notes

- Live-provider interpretation quality remains a pre-submission (Phase 10) check; Phase 9 used FakeModelClient only.
- Operator UI state does not survive operator-server restart (intentional).
- `action_key` is run-scoped; TeamMail reconciliation uses `operation_id`.

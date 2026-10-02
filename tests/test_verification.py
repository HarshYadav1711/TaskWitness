"""Phase 6 verification unit tests (no Chromium)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from taskwitness.browser.talentdesk import VisibleCandidate
from taskwitness.control import AlwaysApprove, AlwaysReject, InMemoryProgressCollector
from taskwitness.journal import ActionState, Journal
from taskwitness.schemas import ActionType, Authority, TaskSpec
from taskwitness.testing.fakes import FakeTalentDesk, FakeTeamMail
from taskwitness.verification.evidence import (
    EvidencePathError,
    EvidenceWriter,
    sanitize_run_id,
    validate_manifest_hashes,
)
from taskwitness.verification.expectations import (
    ExpectationKind,
    derive_expectations,
    expected_candidates,
)
from taskwitness.verification.types import (
    CheckStatus,
    OverallVerificationStatus,
    aggregate_overall,
)
from taskwitness.verification.verifier import GoalVerifier
from taskwitness.workflow import (
    RecruitingWorkflow,
    WorkflowConfig,
    followup_subject,
    make_operation_id,
)

ROOT = Path(__file__).resolve().parents[1]
CSV = str(ROOT / "data" / "candidates.csv")


def _base_spec(**authority_overrides) -> TaskSpec:
    auth = {"send_message": False, "change_stage": True}
    auth.update(authority_overrides)
    return TaskSpec(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[
            ActionType.prepare_followup,
            ActionType.set_stage,
            ActionType.send_message,
        ],
        target_stage="Interview Ready",
        authority=Authority(**auth),
    )


def _variation_spec() -> TaskSpec:
    return TaskSpec(
        source_file=CSV,
        role="Backend Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup],
        target_stage=None,
        authority=Authority(send_message=False, change_stage=False),
    )


def _seed_ai_desk() -> FakeTalentDesk:
    desk = FakeTalentDesk()
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-001",
            name="Asha Verma",
            email="asha.verma@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Phone Screen",
        )
    )
    desk.seed(
        VisibleCandidate(
            candidate_id="CAND-002",
            name="Jordan Lee",
            email="jordan.lee@example.test",
            role="AI Engineering",
            status="Shortlisted",
            current_stage="Recruiter Review",
        )
    )
    return desk


def _cfg(**overrides) -> WorkflowConfig:
    send_auth = bool(overrides.get("authority_send_message", False))
    set_stage = bool(overrides.get("set_stage_requested", True))
    if set_stage:
        spec = _base_spec(send_message=send_auth)
    else:
        spec = TaskSpec(
            source_file=CSV,
            role="AI Engineering",
            candidate_status="Shortlisted",
            actions=[ActionType.prepare_followup, ActionType.send_message],
            target_stage=None,
            authority=Authority(send_message=send_auth, change_stage=False),
        )
    data = dict(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        prepare_followups=True,
        set_stage_requested=True,
        send_message_requested=True,
        target_stage="Interview Ready",
        authority_change_stage=True,
        authority_send_message=False,
        task_spec_json=spec.model_dump_json(),
    )
    data.update(overrides)
    if "task_spec_json" not in overrides:
        data["task_spec_json"] = spec.model_dump_json()
    return WorkflowConfig(**data)


# --- A. Postcondition derivation ----------------------------------------


def test_expected_candidates_from_taskspec_csv_not_executor():
    spec = _base_spec()
    cands = expected_candidates(spec)
    assert [c.candidate_id for c in cands] == ["CAND-001", "CAND-002"]


def test_set_stage_produces_stage_postcondition():
    exps = derive_expectations(_base_spec())
    stages = [e for e in exps if e.kind is ExpectationKind.stage_equals]
    assert len(stages) == 2
    assert all(e.expected_value == "Interview Ready" for e in stages)


def test_prepare_followup_produces_artifact_postcondition():
    exps = derive_expectations(_base_spec())
    followups = [e for e in exps if e.kind is ExpectationKind.followup_artifact]
    assert len(followups) == 2
    for e in followups:
        op = make_operation_id(candidate_id=e.candidate.candidate_id, role=e.candidate.role)
        assert e.operation_id == op


def test_send_message_produces_exactly_one_postcondition():
    exps = derive_expectations(_base_spec())
    sends = [e for e in exps if e.kind is ExpectationKind.send_exactly_one]
    assert len(sends) == 2
    assert all(not e.incomplete_ok for e in sends)


def test_rejected_send_incomplete_with_safety_absent():
    journal_actions = []
    # Simulate rejected journal records without full Journal plumbing.
    from taskwitness.journal.types import ActionRecord

    for cid in ("CAND-001", "CAND-002"):
        journal_actions.append(
            ActionRecord(
                action_key=f"k-{cid}",
                run_id="r",
                candidate_id=cid,
                action_type="send_message",
                operation_id=make_operation_id(candidate_id=cid, role="AI Engineering"),
                payload_json="{}",
                state=ActionState.rejected,
                attempt_count=0,
                created_at="t",
                updated_at="t",
                last_error=None,
                recovery_note="rejected",
            )
        )
    exps = derive_expectations(_base_spec(), journal_actions=journal_actions)
    absent = [e for e in exps if e.kind is ExpectationKind.send_absent]
    incomplete = [
        e
        for e in exps
        if e.kind is ExpectationKind.send_exactly_one and e.incomplete_ok
    ]
    assert len(absent) == 2
    assert len(incomplete) == 2


def test_action_absent_no_positive_send_or_stage_requirement():
    exps = derive_expectations(_variation_spec())
    assert not any(e.kind is ExpectationKind.send_exactly_one for e in exps)
    assert not any(e.kind is ExpectationKind.stage_equals for e in exps)
    assert any(e.kind is ExpectationKind.followup_artifact for e in exps)
    assert any(e.kind is ExpectationKind.send_absent for e in exps)
    assert any(e.kind is ExpectationKind.stage_unchanged for e in exps)


# --- B. Overall result / verifier with fakes ----------------------------


def test_all_required_checks_passed_verified_complete(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    assert result.run_id
    # Execution completed — verification is independent.
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.overall_status is OverallVerificationStatus.passed
    assert vr.verified_complete is True
    assert vr.expected_candidate_ids == ["CAND-001", "CAND-002"]
    journal.close()


def test_rejected_requested_send_incomplete(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(),
        approval_provider=AlwaysReject(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.overall_status is OverallVerificationStatus.incomplete
    assert vr.verified_complete is False
    assert any(c.status is CheckStatus.incomplete for c in vr.checks)
    assert any(
        c.status is CheckStatus.passed and "Rejected send" in c.description
        for c in vr.checks
    )
    journal.close()


def test_mismatched_final_state_failed(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    # Corrupt TalentDesk stage after execution.
    desk.candidates["CAND-001"] = VisibleCandidate(
        candidate_id="CAND-001",
        name="Asha Verma",
        email="asha.verma@example.test",
        role="AI Engineering",
        status="Shortlisted",
        current_stage="Phone Screen",
    )
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.overall_status is OverallVerificationStatus.failed
    assert vr.verified_complete is False
    journal.close()


def test_unavailable_target_state_blocked(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()

    class BrokenDesk(FakeTalentDesk):
        def read_candidate(self):
            raise RuntimeError("TalentDesk unavailable")

    broken = BrokenDesk()
    broken.candidates = desk.candidates
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=broken, mail=mail)
    assert any(c.status is CheckStatus.blocked for c in vr.checks)
    assert vr.verified_complete is False
    assert vr.overall_status is OverallVerificationStatus.blocked or vr.overall_status is OverallVerificationStatus.failed
    # If some stage checks blocked and send checks still pass, overall is blocked
    # unless a failed check exists. Broken desk only affects stage reads.
    journal.close()


def test_recovered_send_verifies_as_passed(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    mail.fail_send_unknown_once = True
    recover_spec = TaskSpec(
        source_file=CSV,
        role="AI Engineering",
        candidate_status="Shortlisted",
        actions=[ActionType.prepare_followup, ActionType.send_message],
        target_stage=None,
        authority=Authority(send_message=True, change_stage=False),
    )
    result = RecruitingWorkflow(
        _cfg(
            set_stage_requested=False,
            target_stage=None,
            authority_change_stage=False,
            authority_send_message=True,
            task_spec_json=recover_spec.model_dump_json(),
        ),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    assert any(c.send and c.send.recovered for c in result.candidate_results)
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.verified_complete is True
    send_checks = [c for c in vr.checks if c.action == "send_message"]
    assert all(c.status is CheckStatus.passed for c in send_checks)
    journal.close()


def test_duplicate_sent_count_fails(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    op = make_operation_id(candidate_id="CAND-001", role="AI Engineering")
    mail.inject_sent(
        message_id="DUP-EXTRA",
        recipient="asha.verma@example.test",
        subject=followup_subject("AI Engineering"),
        body="x",
        operation_id=op,
    )
    assert mail.count_sent_by_operation_id(op) > 1
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.overall_status is OverallVerificationStatus.failed
    assert any("duplicate" in (c.observed or "").lower() for c in vr.checks)
    journal.close()


def test_executor_success_not_treated_as_proof(tmp_path: Path):
    """Journal SUCCEEDED + corrupted app state => verification FAILED."""
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    assert result.ok
    # Wipe sent artifacts — journal still says succeeded.
    mail.sent.clear()
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.verified_complete is False
    assert vr.overall_status is OverallVerificationStatus.failed
    journal.close()


# --- C. Evidence --------------------------------------------------------


def test_evidence_package_and_manifest(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    progress = InMemoryProgressCollector()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        progress=progress,
        close_journal=False,
    ).run()
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    writer = EvidenceWriter(tmp_path / "evidence")
    package = writer.write(result=vr, journal=journal, progress_events=progress.events)

    assert package.exists()
    assert (package / "task_spec.json").exists()
    assert (package / "verification.json").exists()
    assert (package / "journal.json").exists()
    assert (package / "summary.md").exists()
    assert (package / "manifest.json").exists()
    assert (package / "progress.jsonl").exists()

    spec_snap = json.loads((package / "task_spec.json").read_text(encoding="utf-8"))
    assert spec_snap["authority"]["send_message"] is True
    assert spec_snap["authority"]["change_stage"] is True

    ver = json.loads((package / "verification.json").read_text(encoding="utf-8"))
    assert ver["checks"]
    assert ver["run_id"] == result.run_id

    jexport = json.loads((package / "journal.json").read_text(encoding="utf-8"))
    assert jexport["run"]["run_id"] == result.run_id
    assert all(a["run_id"] == result.run_id for a in jexport["actions"])

    mismatches = validate_manifest_hashes(package)
    assert mismatches == []

    # Hash recompute matches listed values.
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    for art in manifest["artifacts"]:
        path = package / art["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == art["sha256"]
        assert path.stat().st_size == art["size_bytes"]
    journal.close()


def test_summary_exposes_incomplete_work(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(),
        approval_provider=AlwaysReject(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    package = EvidenceWriter(tmp_path / "evidence").write(result=vr, journal=journal)
    summary = (package / "summary.md").read_text(encoding="utf-8")
    assert "INCOMPLETE" in summary
    assert "Incomplete work" in summary
    assert "None." not in summary.split("## Incomplete work")[1].split("##")[0]
    journal.close()


def test_evidence_path_traversal_rejected():
    with pytest.raises(EvidencePathError):
        sanitize_run_id("../etc/passwd")
    with pytest.raises(EvidencePathError):
        sanitize_run_id("not a uuid!!!")
    with pytest.raises(EvidencePathError):
        EvidenceWriter(Path("evidence")).package_dir("../../secret")


def test_evidence_generated_on_failed_verification(tmp_path: Path):
    journal = Journal(tmp_path / "j.sqlite3")
    desk = _seed_ai_desk()
    mail = FakeTeamMail()
    result = RecruitingWorkflow(
        _cfg(authority_send_message=True),
        approval_provider=AlwaysApprove(),
        desk=desk,
        mail=mail,
        journal=journal,
        close_journal=False,
    ).run()
    mail.sent.clear()
    v = GoalVerifier(journal=journal, source_root=ROOT, skip_app_wait=True)
    vr = v.verify(result.run_id, desk=desk, mail=mail)
    assert vr.verified_complete is False
    package = EvidenceWriter(tmp_path / "evidence").write(result=vr, journal=journal)
    assert (package / "summary.md").exists()
    assert "FAILED" in (package / "summary.md").read_text(encoding="utf-8")
    journal.close()


def test_aggregate_overall_priority():
    from taskwitness.verification.types import PostconditionCheck

    checks = [
        PostconditionCheck("a", "d", "e", "o", CheckStatus.incomplete),
        PostconditionCheck("b", "d", "e", "o", CheckStatus.failed),
    ]
    assert aggregate_overall(checks) is OverallVerificationStatus.failed


def test_no_production_demo_db_in_verification_modules():
    import inspect

    import taskwitness.verification.evidence as evidence_mod
    import taskwitness.verification.expectations as expectations_mod
    import taskwitness.verification.verifier as verifier_mod
    import taskwitness.verify_demo as verify_demo_mod

    for mod in (evidence_mod, expectations_mod, verifier_mod, verify_demo_mod):
        src = inspect.getsource(mod)
        assert "demo_env.db" not in src
        assert "demo_env.sqlite3" not in src
        assert "get_db_path" not in src

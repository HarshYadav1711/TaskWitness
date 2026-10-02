"""Phase 8 assignment-level scenario tests (operator UI + real synthetic apps)."""

from __future__ import annotations

from pathlib import Path

from taskwitness.assessment_accept import (
    run_base_scenario,
    run_recovery_scenario,
    run_variation_scenario,
)

# Full-stack scenarios are slower; keep to the three required assignment demos.


def test_assessment_base_scenario(tmp_path: Path):
    result = run_base_scenario(work_dir=tmp_path / "base", headed=False, slow_mo_ms=0)
    assert result.status == "PASS", result.error or result.assertions
    assert result.verified_complete is True
    assert result.execution_state == "completed"
    assert result.verification_status == "passed"
    assert result.details.get("candidate_count") == 2


def test_assessment_variation_scenario(tmp_path: Path):
    result = run_variation_scenario(
        work_dir=tmp_path / "variation", headed=False, slow_mo_ms=0
    )
    assert result.status == "PASS", result.error or result.assertions
    assert result.verified_complete is True
    assert result.details.get("messages_sent") == 0


def test_assessment_recovery_scenario(tmp_path: Path):
    result = run_recovery_scenario(
        work_dir=tmp_path / "recovery", headed=False, slow_mo_ms=0
    )
    assert result.status == "PASS", result.error or result.assertions
    assert result.verified_complete is True
    assert result.details.get("attempt_count") == 1
    assert result.details.get("sent_matches") == 1
    assert result.details.get("recovered_operation_id")

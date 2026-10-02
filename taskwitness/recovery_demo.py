"""Phase 5 recovery development harness — ambiguous send + journal reconciliation.

Not the final operator UI. Uses the synthetic TeamMail one-shot fault seam.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from taskwitness.control import AlwaysApprove, CallbackProgressSink, MultiplexProgressSink, print_progress
from taskwitness.control.progress import InMemoryProgressCollector
from taskwitness.journal import ActionState, Journal, default_journal_path
from taskwitness.schemas import ActionType, Authority, RunState, TaskSpec
from taskwitness.workflow import RecruitingWorkflow, config_from_taskspec, make_operation_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run TaskWitness Phase-5 ambiguous-send recovery demo. "
            "Activates the synthetic TeamMail fail_after_send_commit_once fault."
        )
    )
    parser.add_argument(
        "--from-taskspec",
        default="examples/base-plan.json",
        help="TaskSpec JSON (default: base plan; send_message authority false).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--slow-mo", type=int, default=0)
    parser.add_argument(
        "--journal",
        default=None,
        help="Journal SQLite path (default: .taskwitness/journal.sqlite3).",
    )
    parser.add_argument(
        "--reset-journal",
        action="store_true",
        help="Wipe TaskWitness journal before running (does not reset demo_env).",
    )
    parser.add_argument(
        "--arm-fault",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Arm demo_env fail_after_send_commit_once (test/setup only; default on).",
    )
    parser.add_argument(
        "--single-candidate",
        action="store_true",
        help="Limit CSV filter to first matching candidate via a temp CSV rewrite.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After execution finishes, run independent verification and write evidence.",
    )
    parser.add_argument(
        "--evidence-root",
        default=None,
        help="Evidence output root when --verify is set (default: ./evidence).",
    )
    return parser


def _arm_fault() -> None:
    # Test/setup only — not TaskWitness production mutation of business state.
    from demo_env.app import get_db_path
    from demo_env.db import arm_fail_after_send_commit_once, connect

    conn = connect(get_db_path())
    try:
        arm_fail_after_send_commit_once(conn)
        conn.commit()
    finally:
        conn.close()
    print("Armed synthetic fault: fail_after_send_commit_once")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = TaskSpec.model_validate_json(
        Path(args.from_taskspec).read_text(encoding="utf-8")
    )
    # Prefer prepare + send for a clear recovery demo when base plan includes stage.
    # Keep the loaded TaskSpec authority intact (do not mutate).
    original_authority = spec.authority.model_copy()

    journal_path = Path(args.journal) if args.journal else default_journal_path()
    journal = Journal(journal_path)
    if args.reset_journal:
        journal.reset()
        print(f"Journal reset: {journal_path}")

    if args.arm_fault:
        _arm_fault()

    config, _ = config_from_taskspec(
        spec, headed=args.headed, base_url=args.base_url
    )
    config.slow_mo_ms = args.slow_mo

    collector = InMemoryProgressCollector()
    progress = MultiplexProgressSink(
        collector,
        CallbackProgressSink(print_progress),
    )

    print("TaskWitness Phase-5 recovery demo")
    print(f"  taskspec={args.from_taskspec}")
    print(f"  journal={journal_path}")
    print(
        f"  authority: change_stage={spec.authority.change_stage} "
        f"send_message={spec.authority.send_message}"
    )
    print("  journal is local assessment state (separate from demo_env)")
    print()

    # Keep journal open across run for post-inspection (workflow would close owned journal).
    result = RecruitingWorkflow(
        config,
        approval_provider=AlwaysApprove(),
        progress=progress,
        journal=journal,
        close_journal=False,
    ).run()

    assert spec.authority == original_authority

    send_actions = []
    if result.run_id:
        send_actions = [
            a
            for a in journal.list_actions(result.run_id)
            if a.action_type == ActionType.send_message.value
        ]

    payload = {
        "run_state": result.run_state.value,
        "run_id": result.run_id,
        "ok": result.ok,
        "error": result.error,
        "authority_unchanged": original_authority.model_dump(),
        "candidates": [asdict(c) for c in result.candidate_results],
        "send_actions": [
            {
                "action_key": a.action_key,
                "candidate_id": a.candidate_id,
                "operation_id": a.operation_id,
                "state": a.state.value,
                "attempt_count": a.attempt_count,
                "recovery_note": a.recovery_note,
                "last_error": a.last_error,
            }
            for a in send_actions
        ],
    }
    print()
    print("Execution completed." if result.run_state in {RunState.completed, RunState.partial} else "Execution did not complete.")
    print(json.dumps(payload, indent=2))

    exit_code = 1
    if result.run_state in {RunState.completed, RunState.partial}:
        exit_code = 0

    if args.verify and result.run_id:
        from taskwitness.verify_demo import run_verification
        from taskwitness.verification.evidence import default_evidence_root
        from taskwitness.verification.types import OverallVerificationStatus

        evidence_root = (
            Path(args.evidence_root) if args.evidence_root else default_evidence_root()
        )
        print()
        print("Starting independent verification (fresh browser session)...")
        vresult, package = run_verification(
            run_id=result.run_id,
            journal=journal,
            base_url=args.base_url,
            headed=args.headed,
            evidence_root=evidence_root,
            source_root=Path("."),
            progress=collector,
        )
        print(
            json.dumps(
                {
                    "overall_status": vresult.overall_status.value,
                    "verified_complete": vresult.verified_complete,
                    "evidence_path": str(package),
                },
                indent=2,
            )
        )
        if vresult.verified_complete:
            print("Goal verified.")
        elif vresult.overall_status is OverallVerificationStatus.incomplete:
            print("Goal incomplete (not verified complete).")
        else:
            print("Verification did not pass.")
            exit_code = 1

    journal.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

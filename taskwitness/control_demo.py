"""Phase 4 development harness — authority, approval, pause / progress.

Not the final operator UI. Terminal controls only.
Control state is in-memory for the duration of the process.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from taskwitness.control import (
    AlwaysApprove,
    AlwaysReject,
    CallbackProgressSink,
    InMemoryProgressCollector,
    MultiplexProgressSink,
    RunControl,
    TerminalApprovalProvider,
    print_progress,
)
from taskwitness.control.progress import ProgressEvent
from taskwitness.journal import Journal, default_journal_path
from taskwitness.schemas import RunState, TaskSpec
from taskwitness.workflow import RecruitingWorkflow, config_from_taskspec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run TaskWitness Phase-4 human-control demo "
            "(approval-gated send / stage, pause, progress)."
        )
    )
    parser.add_argument(
        "--from-taskspec",
        required=True,
        help="Path to a TaskSpec JSON (canonical intent contract).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show Chromium (default: headed).",
    )
    parser.add_argument("--slow-mo", type=int, default=0)
    approval = parser.add_mutually_exclusive_group()
    approval.add_argument(
        "--approve-all",
        action="store_true",
        help="Non-interactive: approve every gated action.",
    )
    approval.add_argument(
        "--reject-all",
        action="store_true",
        help="Non-interactive: reject every gated action.",
    )
    parser.add_argument(
        "--console-control",
        action="store_true",
        help=(
            "Run workflow in a worker thread and accept pause/resume "
            "commands on stdin (p / r / quit)."
        ),
    )
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


def _provider_from_args(args: argparse.Namespace):
    if args.approve_all:
        return AlwaysApprove()
    if args.reject_all:
        return AlwaysReject()
    return TerminalApprovalProvider()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = TaskSpec.model_validate_json(
        Path(args.from_taskspec).read_text(encoding="utf-8")
    )
    # Snapshot original authority — approval must never mutate TaskSpec.
    original_authority = spec.authority.model_copy()

    config, _ = config_from_taskspec(
        spec,
        headed=args.headed,
        base_url=args.base_url,
    )
    config.slow_mo_ms = args.slow_mo

    collector = InMemoryProgressCollector()
    progress = MultiplexProgressSink(
        collector,
        CallbackProgressSink(print_progress),
    )

    def on_state(state: RunState) -> None:
        progress.emit(
            ProgressEvent(
                run_state=state,
                message=f"Run state -> {state.value}",
                event_type="state",
            )
        )

    journal_path = Path(args.journal) if args.journal else default_journal_path()
    journal = Journal(journal_path)
    if args.reset_journal:
        journal.reset()
        print(f"Journal reset: {journal_path}")

    control = RunControl(on_state_change=on_state)
    provider = _provider_from_args(args)
    workflow = RecruitingWorkflow(
        config,
        run_control=control,
        approval_provider=provider,
        progress=progress,
        journal=journal,
        close_journal=False,
    )

    print("TaskWitness Phase-4 control demo")
    print(f"  taskspec={args.from_taskspec}")
    print(f"  journal={journal_path}")
    print(f"  role={config.role!r} status={config.candidate_status!r}")
    print(
        f"  actions: prepare={config.prepare_followups} "
        f"set_stage={config.set_stage_requested} "
        f"send={config.send_message_requested}"
    )
    print(
        f"  authority: change_stage={config.authority_change_stage} "
        f"send_message={config.authority_send_message}"
    )
    print(f"  headed={config.headed} base_url={config.base_url}")
    print("  approval/pause state: in-memory; effects journaled locally")
    if args.console_control:
        print("  console control: type 'p' pause, 'r' resume, 'q' quit listener")
    print()

    result_box: dict = {}

    def _run() -> None:
        result_box["result"] = workflow.run()

    if args.console_control:
        worker = threading.Thread(target=_run, name="tw-workflow", daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                try:
                    line = input().strip().lower()
                except EOFError:
                    break
                if line in {"p", "pause"}:
                    control.request_pause()
                    print("[control] pause requested (cooperative checkpoint)")
                elif line in {"r", "resume"}:
                    control.resume()
                    print("[control] resume requested")
                elif line in {"q", "quit"}:
                    print("[control] listener stopped; waiting for workflow")
                    break
        finally:
            worker.join()
    else:
        _run()

    result = result_box["result"]
    # Prove TaskSpec authority was not mutated by approvals.
    assert spec.authority.send_message == original_authority.send_message
    assert spec.authority.change_stage == original_authority.change_stage

    payload = {
        "run_state": result.run_state.value,
        "run_id": result.run_id,
        "ok": result.ok,
        "selected_candidate_ids": result.selected_candidate_ids,
        "error": result.error,
        "authority_unchanged": {
            "send_message": spec.authority.send_message,
            "change_stage": spec.authority.change_stage,
        },
        "candidates": [asdict(c) for c in result.candidate_results],
        "progress_event_count": len(collector.events),
    }
    print()
    print(
        "Execution completed."
        if result.run_state in {RunState.completed, RunState.partial}
        else "Execution did not complete."
    )
    print(json.dumps(payload, indent=2))

    exit_code = 0 if result.run_state in {RunState.completed, RunState.partial} else 1

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

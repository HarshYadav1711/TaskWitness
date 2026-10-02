"""Phase 2/4 developer harness — headed/headless recruiting browser demo.

Prefer `python -m taskwitness.control_demo` for approval/pause demos.
This module remains for deterministic draft/stage runs without interactive approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from taskwitness.control import AlwaysApprove, AlwaysReject, TerminalApprovalProvider
from taskwitness.schemas import TaskSpec
from taskwitness.workflow import RecruitingWorkflow, WorkflowConfig, config_from_taskspec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run TaskWitness deterministic browser workflow."
    )
    parser.add_argument("--role", default="AI Engineering")
    parser.add_argument("--status", default="Shortlisted", dest="candidate_status")
    parser.add_argument("--source-file", default="data/candidates.csv")
    parser.add_argument("--target-stage", default=None)
    parser.add_argument(
        "--prepare-followups",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create TeamMail drafts (default: true).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show Chromium (default: headed). Use --headless for CI.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Optional Playwright slow_mo ms for demo pacing (0 disables).",
    )
    parser.add_argument(
        "--from-taskspec",
        default=None,
        help=(
            "Optional path to a TaskSpec JSON. Authority gates are enforced; "
            "CLI flags cannot restore authority the TaskSpec did not grant. "
            "For interactive approval prefer taskwitness.control_demo."
        ),
    )
    approval = parser.add_mutually_exclusive_group()
    approval.add_argument(
        "--approve-all",
        action="store_true",
        help="When using --from-taskspec, approve gated actions non-interactively.",
    )
    approval.add_argument(
        "--reject-all",
        action="store_true",
        help="When using --from-taskspec, reject gated actions non-interactively.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = None

    if args.from_taskspec:
        spec = TaskSpec.model_validate_json(
            Path(args.from_taskspec).read_text(encoding="utf-8")
        )
        config, _ = config_from_taskspec(
            spec,
            headed=args.headed,
            base_url=args.base_url,
        )
        # CLI cannot restore authority TaskSpec did not grant.
        # --target-stage only applies when set_stage is already authorized.
        if args.target_stage and config.authority_change_stage and config.set_stage_requested:
            config.target_stage = args.target_stage
        # CLI cannot enable prepare if TaskSpec omitted it; can only disable.
        if not args.prepare_followups:
            config.prepare_followups = False
        config.slow_mo_ms = args.slow_mo
        if args.approve_all:
            provider = AlwaysApprove()
        elif args.reject_all:
            provider = AlwaysReject()
        elif config.send_message_requested and not config.authority_send_message:
            provider = TerminalApprovalProvider()
        elif config.set_stage_requested and not config.authority_change_stage:
            provider = TerminalApprovalProvider()
        else:
            provider = AlwaysApprove()
    else:
        # Legacy CLI path: never enables send_message; stage allowed when requested.
        config = WorkflowConfig(
            source_file=args.source_file,
            role=args.role,
            candidate_status=args.candidate_status,
            prepare_followups=args.prepare_followups,
            set_stage_requested=bool(args.target_stage),
            send_message_requested=False,
            target_stage=args.target_stage,
            authority_change_stage=bool(args.target_stage),
            authority_send_message=False,
            base_url=args.base_url,
            headed=args.headed,
            slow_mo_ms=args.slow_mo,
        )
        provider = AlwaysApprove()

    print("TaskWitness browser demo")
    print(f"  role={config.role!r} status={config.candidate_status!r}")
    print(
        f"  set_stage={config.set_stage_requested} target={config.target_stage!r} "
        f"prepare={config.prepare_followups} send={config.send_message_requested}"
    )
    print(
        f"  authority change_stage={config.authority_change_stage} "
        f"send_message={config.authority_send_message}"
    )
    print(f"  headed={config.headed} base_url={config.base_url}")

    result = RecruitingWorkflow(config, approval_provider=provider).run()
    payload = {
        "run_state": result.run_state.value,
        "ok": result.ok,
        "selected_candidate_ids": result.selected_candidate_ids,
        "error": result.error,
        "candidates": [asdict(c) for c in result.candidate_results],
    }
    print(json.dumps(payload, indent=2))
    if result.run_state.value in {"completed", "partial"}:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

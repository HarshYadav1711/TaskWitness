"""Interpret a plain-English recruiting goal (Phase 3).

Default: interpret only — no browser side effects.
Optional --execute: hand READY TaskSpec to the Phase 4 control-aware workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from taskwitness.control import AlwaysApprove, AlwaysReject, TerminalApprovalProvider
from taskwitness.interpretation import (
    GoalInterpreter,
    InterpretationResult,
    InterpretationStatus,
    ModelClientError,
)
from taskwitness.workflow import RecruitingWorkflow, config_from_taskspec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interpret a TaskWitness recruiting goal into a validated TaskSpec."
    )
    parser.add_argument("--goal", required=True, help="Plain-English recruiting goal.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="If READY, run the browser workflow with Phase-4 authority gates.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Browser mode when --execute is set (default: headed).",
    )
    parser.add_argument("--slow-mo", type=int, default=0)
    approval = parser.add_mutually_exclusive_group()
    approval.add_argument(
        "--approve-all",
        action="store_true",
        help="Non-interactive approve for gated actions during --execute.",
    )
    approval.add_argument(
        "--reject-all",
        action="store_true",
        help="Non-interactive reject for gated actions during --execute.",
    )
    return parser


def result_to_dict(result: InterpretationResult) -> dict:
    payload = {
        "status": result.status.value,
        "original_goal": result.original_goal,
        "clarification_question": result.clarification_question,
        "error": result.error,
        "task_spec": None,
    }
    if result.task_spec is not None:
        payload["task_spec"] = result.task_spec.model_dump(mode="json")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        interpreter = GoalInterpreter.from_env()
    except ModelClientError as exc:
        print(json.dumps({
            "status": InterpretationStatus.model_error.value,
            "original_goal": args.goal,
            "task_spec": None,
            "clarification_question": None,
            "error": str(exc),
        }, indent=2))
        return 2

    result = interpreter.interpret(args.goal)
    print(json.dumps(result_to_dict(result), indent=2))

    if result.status != InterpretationStatus.ready:
        return 1 if result.status != InterpretationStatus.needs_clarification else 3

    if not args.execute:
        return 0

    assert result.task_spec is not None
    # Preserve original authority for post-run inspection.
    original_authority = result.task_spec.authority.model_copy()
    config, _ = config_from_taskspec(
        result.task_spec,
        headed=args.headed,
        base_url=args.base_url,
    )
    config.slow_mo_ms = args.slow_mo
    if args.approve_all:
        provider = AlwaysApprove()
    elif args.reject_all:
        provider = AlwaysReject()
    else:
        provider = TerminalApprovalProvider()
    run = RecruitingWorkflow(config, approval_provider=provider).run()
    assert result.task_spec.authority == original_authority
    print(json.dumps({
        "execution": {
            "run_state": run.run_state.value,
            "ok": run.ok,
            "selected_candidate_ids": run.selected_candidate_ids,
            "error": run.error,
            "authority_unchanged": original_authority.model_dump(),
            "candidates": [asdict(c) for c in run.candidate_results],
        }
    }, indent=2))
    if run.run_state.value in {"completed", "partial"}:
        return 0
    return 4


if __name__ == "__main__":
    sys.exit(main())

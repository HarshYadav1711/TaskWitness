"""Interpret a plain-English recruiting goal (Phase 3).

Default: interpret only — no browser side effects.
Optional --execute: hand READY TaskSpec to the existing Phase 2 workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from taskwitness.interpretation import (
    GoalInterpreter,
    InterpretationResult,
    InterpretationStatus,
    ModelClientError,
)
from taskwitness.interpretation.client import ModelConfig
from taskwitness.workflow import RecruitingWorkflow, config_from_taskspec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interpret a TaskWitness recruiting goal into a validated TaskSpec."
    )
    parser.add_argument("--goal", required=True, help="Plain-English recruiting goal.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="If READY, run the existing Phase-2 browser workflow (never sends).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Browser mode when --execute is set (default: headed).",
    )
    parser.add_argument("--slow-mo", type=int, default=0)
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
    config, _deferred = config_from_taskspec(
        result.task_spec,
        headed=args.headed,
        base_url=args.base_url,
    )
    config.slow_mo_ms = args.slow_mo
    run = RecruitingWorkflow(config).run()
    print(json.dumps({
        "execution": {
            "ok": run.ok,
            "selected_candidate_ids": run.selected_candidate_ids,
            "deferred_actions": run.deferred_actions,
            "error": run.error,
            "candidates": [asdict(c) for c in run.candidate_results],
        }
    }, indent=2))
    return 0 if run.ok else 4


if __name__ == "__main__":
    sys.exit(main())

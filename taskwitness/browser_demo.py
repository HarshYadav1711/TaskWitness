"""Phase 2 developer harness — headed/headless recruiting browser demo.

Not the final operator UI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from dataclasses import asdict

from taskwitness.workflow import RecruitingWorkflow, WorkflowConfig, config_from_taskspec
from taskwitness.schemas import TaskSpec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run TaskWitness Phase-2 deterministic browser workflow."
    )
    parser.add_argument("--role", default="AI Engineering")
    parser.add_argument("--status", default="Shortlisted", dest="candidate_status")
    parser.add_argument("--source-file", default="data/candidates.csv")
    parser.add_argument("--target-stage", default=None)
    parser.add_argument(
        "--prepare-followups",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create TeamMail drafts (default: true). Never sends.",
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
        help="Optional path to a TaskSpec JSON. send_message is deferred.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    deferred: list[str] = []

    if args.from_taskspec:
        spec = TaskSpec.model_validate_json(
            Path(args.from_taskspec).read_text(encoding="utf-8")
        )
        config, deferred = config_from_taskspec(
            spec,
            headed=args.headed,
            base_url=args.base_url,
        )
        # Do not let CLI flags re-enable an authority-deferred stage change.
        if (
            args.target_stage
            and "set_stage:deferred_until_authority_phase" not in deferred
        ):
            config.target_stage = args.target_stage
        config.prepare_followups = args.prepare_followups
        config.slow_mo_ms = args.slow_mo
    else:
        config = WorkflowConfig(
            source_file=args.source_file,
            role=args.role,
            candidate_status=args.candidate_status,
            prepare_followups=args.prepare_followups,
            target_stage=args.target_stage,
            base_url=args.base_url,
            headed=args.headed,
            slow_mo_ms=args.slow_mo,
        )

    print("TaskWitness Phase-2 browser demo")
    print(f"  role={config.role!r} status={config.candidate_status!r}")
    print(f"  target_stage={config.target_stage!r} prepare_followups={config.prepare_followups}")
    print(f"  headed={config.headed} base_url={config.base_url}")
    if deferred:
        print("  deferred:", ", ".join(deferred))

    result = RecruitingWorkflow(config).run()
    payload = {
        "ok": result.ok,
        "selected_candidate_ids": result.selected_candidate_ids,
        "deferred_actions": result.deferred_actions + deferred,
        "error": result.error,
        "candidates": [asdict(c) for c in result.candidate_results],
    }
    print(json.dumps(payload, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

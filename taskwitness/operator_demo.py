"""Start the TaskWitness operator console (Phase 7).

Synthetic apps remain on http://127.0.0.1:8000.
Operator defaults to http://127.0.0.1:8010.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from taskwitness.operator.app import create_app
from taskwitness.operator.runtime import OperatorRuntime
from taskwitness.schemas import TaskSpec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the TaskWitness local operator console."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Synthetic TalentDesk/TeamMail base URL.",
    )
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show Chromium for execution and verification (default: headed).",
    )
    parser.add_argument("--slow-mo", type=int, default=0, help="Optional Playwright slow-mo ms.")
    parser.add_argument(
        "--demo-plan",
        default=None,
        help=(
            "DEVELOPMENT ONLY: path to a validated TaskSpec JSON. "
            "Enables Validated Plan Demo Mode (not live NL interpretation)."
        ),
    )
    parser.add_argument("--journal", default=None)
    parser.add_argument("--evidence-root", default="evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    demo_spec = None
    if args.demo_plan:
        path = Path(args.demo_plan)
        demo_spec = TaskSpec.model_validate_json(path.read_text(encoding="utf-8"))

    runtime = OperatorRuntime(
        base_url=args.base_url,
        headed=args.headed,
        slow_mo_ms=args.slow_mo,
        journal_path=args.journal,
        evidence_root=args.evidence_root,
        demo_task_spec=demo_spec,
    )
    app = create_app(runtime)

    print("TaskWitness operator")
    print(f"  url=http://{args.host}:{args.port}/operator")
    print(f"  apps={args.base_url}")
    print(f"  headed={args.headed} slow_mo={args.slow_mo}")
    if demo_spec is not None:
        print(f"  VALIDATED PLAN DEMO MODE: {args.demo_plan}")
        print("  (Not live natural-language interpretation.)")
    else:
        print("  mode=natural_language (requires LLM_API_KEY + LLM_MODEL)")
    print("  limitation: one active run at a time; live UI state is in-memory only")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())

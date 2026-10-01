"""Optional live interpretation eval against examples/interpretation_fixtures.json.

Requires LLM_API_KEY and LLM_MODEL. Does not launch Playwright.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from taskwitness.interpretation import GoalInterpreter, InterpretationStatus, ModelClientError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "interpretation_fixtures.json"


def _match_spec(actual: dict, expected: dict) -> list[str]:
    mismatches = []
    for key, exp in expected.items():
        got = actual.get(key)
        if key == "actions":
            if list(got or []) != list(exp):
                mismatches.append(f"actions: {got!r} != {exp!r}")
        elif key == "authority":
            if dict(got or {}) != dict(exp):
                mismatches.append(f"authority: {got!r} != {exp!r}")
        else:
            if got != exp:
                mismatches.append(f"{key}: {got!r} != {exp!r}")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live TaskWitness interpretation fixture eval.")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=FIXTURES,
        help="Path to interpretation fixtures JSON.",
    )
    args = parser.parse_args(argv)

    try:
        interpreter = GoalInterpreter.from_env()
    except ModelClientError as exc:
        print(f"MODEL CONFIG ERROR: {exc}")
        return 2

    fixtures = json.loads(args.fixtures.read_text(encoding="utf-8"))
    passed = 0
    checked = 0
    for case in fixtures:
        case_id = case["id"]
        goal = case["goal"]
        expect_status = case["expect_status"]
        if expect_status == "ready_or_policy":
            # Soft live case: either clarification or policy rejection is OK.
            result = interpreter.interpret(goal)
            ok = result.status in {
                InterpretationStatus.needs_clarification,
                InterpretationStatus.policy_rejected,
                InterpretationStatus.ready,
            }
            if result.status == InterpretationStatus.ready and result.task_spec:
                # Ready is only OK if source remains approved after policy.
                ok = result.task_spec.source_file == "data/candidates.csv"
            checked += 1
            print(f"{case_id:28} {'PASS' if ok else 'FAIL'}  ({result.status.value})")
            passed += int(ok)
            continue

        result = interpreter.interpret(goal)
        checked += 1
        if expect_status == "needs_clarification":
            ok = result.status == InterpretationStatus.needs_clarification and result.task_spec is None
            print(f"{case_id:28} {'PASS' if ok else 'FAIL'}  ({result.status.value})")
            passed += int(ok)
            continue

        if expect_status != "ready":
            print(f"{case_id:28} SKIP  unsupported expect_status={expect_status}")
            checked -= 1
            continue

        if result.status != InterpretationStatus.ready or result.task_spec is None:
            print(f"{case_id:28} FAIL  ({result.status.value}) {result.error}")
            continue

        mismatches = _match_spec(
            result.task_spec.model_dump(mode="json"),
            case["expect_task_spec"],
        )
        ok = not mismatches
        detail = "" if ok else "; ".join(mismatches)
        print(f"{case_id:28} {'PASS' if ok else 'FAIL'}  {detail}")
        passed += int(ok)

    print(f"\n{passed}/{checked} fixture expectations matched")
    return 0 if passed == checked and checked > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

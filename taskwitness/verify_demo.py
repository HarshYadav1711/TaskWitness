"""Phase 6 verification/evidence development harness.

Standalone post-run verification by run_id. Not the final operator UI.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from taskwitness.control.progress import InMemoryProgressCollector
from taskwitness.journal import Journal, default_journal_path
from taskwitness.verification.evidence import (
    EvidenceWriter,
    default_evidence_root,
    validate_manifest_hashes,
)
from taskwitness.verification.types import OverallVerificationStatus
from taskwitness.verification.verifier import GoalVerifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently verify a completed TaskWitness run and write an evidence package. "
            "Does not trust executor success as proof of business state."
        )
    )
    parser.add_argument("--run-id", required=True, help="Journal run_id to verify.")
    parser.add_argument(
        "--journal",
        default=None,
        help="Journal SQLite path (default: .taskwitness/journal.sqlite3).",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--headed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show Chromium for the fresh verification session (default: headed).",
    )
    parser.add_argument(
        "--evidence-root",
        default=None,
        help="Evidence output root (default: ./evidence).",
    )
    parser.add_argument(
        "--source-root",
        default=".",
        help="Root for resolving TaskSpec.source_file (default: cwd).",
    )
    return parser


def run_verification(
    *,
    run_id: str,
    journal: Journal,
    base_url: str = "http://127.0.0.1:8000",
    headed: bool = True,
    evidence_root: Path | None = None,
    source_root: Path | None = None,
    progress: InMemoryProgressCollector | None = None,
    desk=None,
    mail=None,
) -> tuple[object, Path]:
    """Verify then write evidence. Returns (VerificationResult, package_dir)."""
    root = evidence_root if evidence_root is not None else default_evidence_root()
    writer = EvidenceWriter(root)
    package = writer.package_dir(run_id)
    package.mkdir(parents=True, exist_ok=True)
    shot_tmp = Path(tempfile.mkdtemp(prefix="tw-verify-shots-"))

    verifier = GoalVerifier(
        journal=journal,
        base_url=base_url,
        headed=headed,
        source_root=source_root,
    )
    result = verifier.verify(
        run_id,
        screenshot_dir=shot_tmp,
        desk=desk,
        mail=mail,
    )
    out = writer.write(
        result=result,
        journal=journal,
        progress_events=progress.events if progress is not None else None,
        screenshot_dir=shot_tmp,
    )
    return result, out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    journal_path = Path(args.journal) if args.journal else default_journal_path()
    journal = Journal(journal_path)
    evidence_root = Path(args.evidence_root) if args.evidence_root else default_evidence_root()

    run = journal.load_run(args.run_id)
    if run is None:
        print(f"Unknown run_id: {args.run_id}", file=sys.stderr)
        journal.close()
        return 2

    print("TaskWitness Phase-6 independent verification")
    print(f"  run_id={args.run_id}")
    print(f"  journal={journal_path}")
    print(f"  execution_state={run.state}")
    print(f"  evidence_root={evidence_root}")
    print("  Opening fresh browser session for verification (not reusing execution session).")
    print()

    try:
        result, package = run_verification(
            run_id=args.run_id,
            journal=journal,
            base_url=args.base_url,
            headed=args.headed,
            evidence_root=evidence_root,
            source_root=Path(args.source_root),
        )
    finally:
        journal.close()

    label = {
        OverallVerificationStatus.passed: "Goal verified.",
        OverallVerificationStatus.incomplete: "Goal incomplete (not verified complete).",
        OverallVerificationStatus.failed: "Verification failed.",
        OverallVerificationStatus.blocked: "Verification blocked.",
    }[result.overall_status]

    counts = result.to_dict()["counts"]
    payload = {
        "run_id": result.run_id,
        "execution_state": run.state,
        "overall_status": result.overall_status.value,
        "verified_complete": result.verified_complete,
        "expected_candidates": result.expected_candidate_ids,
        "counts": counts,
        "evidence_path": str(package),
        "message": label,
    }
    print(json.dumps(payload, indent=2))
    print()
    print(label)
    print(f"Evidence: {package}")

    mismatches = validate_manifest_hashes(package)
    if mismatches:
        print(f"Manifest integrity issues: {mismatches}", file=sys.stderr)
        return 1

    if result.verified_complete:
        return 0
    if result.overall_status is OverallVerificationStatus.incomplete:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

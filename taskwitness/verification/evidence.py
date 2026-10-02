"""Evidence package writer — represents VerificationResult as files.

Does not determine verification truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from taskwitness.control.progress import ProgressEvent
from taskwitness.journal.store import Journal
from taskwitness.schemas import TaskSpec
from taskwitness.verification.types import CheckStatus, OverallVerificationStatus, VerificationResult


class EvidencePathError(ValueError):
    pass


def sanitize_run_id(run_id: str) -> str:
    rid = run_id.strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", rid):
        raise EvidencePathError(f"unsafe run_id for evidence path: {run_id!r}")
    if ".." in rid or "/" in rid or "\\" in rid:
        raise EvidencePathError(f"unsafe run_id for evidence path: {run_id!r}")
    return rid


def default_evidence_root() -> Path:
    return Path("evidence")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _render_summary(
    *,
    result: VerificationResult,
    spec: TaskSpec,
    journal_actions: list[dict[str, Any]],
) -> str:
    status_label = {
        OverallVerificationStatus.passed: "VERIFIED",
        OverallVerificationStatus.incomplete: "INCOMPLETE",
        OverallVerificationStatus.failed: "FAILED",
        OverallVerificationStatus.blocked: "BLOCKED",
    }[result.overall_status]

    lines = [
        "# TaskWitness Run Evidence",
        "",
        f"Run: `{result.run_id}`",
        f"Result: **{status_label}**",
        f"verified_complete: `{str(result.verified_complete).lower()}`",
        f"Generated: {result.generated_at}",
        "",
        "## Goal",
        "",
        f"- source: `{spec.source_file}`",
        f"- role: {spec.role}",
        f"- status: {spec.candidate_status}",
        f"- actions: {', '.join(a.value for a in spec.actions)}",
        f"- authority.send_message: `{spec.authority.send_message}`",
        f"- authority.change_stage: `{spec.authority.change_stage}`",
        "",
        f"Candidates expected: {len(result.expected_candidate_ids)}",
        f"Candidates: {', '.join(result.expected_candidate_ids) or '(none)'}",
        "",
    ]

    by_cand: dict[str, list] = {}
    for check in result.checks:
        key = check.candidate_id or "(global)"
        by_cand.setdefault(key, []).append(check)

    for cand_id, checks in by_cand.items():
        lines.append(f"## {cand_id}")
        lines.append("")
        for c in checks:
            lines.append(
                f"- [{c.status.value.upper()}] {c.description} — "
                f"expected `{c.expected}`; observed `{c.observed}`"
            )
            if c.note:
                lines.append(f"  - note: {c.note}")
        lines.append("")

    recoveries = [
        a
        for a in journal_actions
        if a.get("state") == "recovered" or a.get("recovery_note")
    ]
    if recoveries:
        lines.append("## Recovery")
        lines.append("")
        for a in recoveries:
            if a.get("action_type") != "send_message":
                continue
            lines.append(
                f"- {a.get('candidate_id')}: state=`{a.get('state')}`; "
                f"attempts={a.get('attempt_count')}; "
                f"operation_id=`{a.get('operation_id')}`"
            )
            if a.get("recovery_note"):
                lines.append(f"  - {a['recovery_note']}")
        lines.append("")

    incomplete = [c for c in result.checks if c.status is CheckStatus.incomplete]
    lines.append("## Incomplete work")
    lines.append("")
    if not incomplete:
        lines.append("None.")
    else:
        for c in incomplete:
            lines.append(f"- {c.candidate_id}: {c.description}")
            if c.note:
                lines.append(f"  - {c.note}")
    lines.append("")

    safety = [
        c
        for c in result.checks
        if c.status is CheckStatus.passed and "Sent" in c.description
        and ("absent" in c.description.lower() or "must not" in c.description.lower()
             or "Rejected send" in c.description)
    ]
    if safety:
        lines.append("## Safety verification")
        lines.append("")
        for c in safety:
            lines.append(f"- {c.candidate_id}: {c.description} — PASSED ({c.observed})")
        lines.append("")

    return "\n".join(lines) + "\n"


class EvidenceWriter:
    """Write a run-scoped evidence package under an evidence root."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_evidence_root()

    def package_dir(self, run_id: str) -> Path:
        safe = sanitize_run_id(run_id)
        out = (self.root / safe).resolve()
        root_resolved = self.root.resolve()
        try:
            out.relative_to(root_resolved)
        except ValueError as exc:
            raise EvidencePathError("evidence path escaped configured root") from exc
        return self.root / safe

    def write(
        self,
        *,
        result: VerificationResult,
        journal: Journal,
        progress_events: Iterable[ProgressEvent] | None = None,
        screenshot_dir: Path | None = None,
    ) -> Path:
        out = self.package_dir(result.run_id)
        out.mkdir(parents=True, exist_ok=True)
        shots = out / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)

        if screenshot_dir is not None and screenshot_dir.exists():
            for src in screenshot_dir.glob("*.png"):
                dest = shots / src.name
                if src.resolve() != dest.resolve():
                    dest.write_bytes(src.read_bytes())

        run = journal.load_run(result.run_id)
        if run is None:
            raise ValueError(f"unknown run_id: {result.run_id}")
        spec = journal.load_task_spec(result.run_id)
        action_export = []
        for a in journal.list_actions(result.run_id):
            action_export.append(
                {
                    "action_key": a.action_key,
                    "run_id": a.run_id,
                    "candidate_id": a.candidate_id,
                    "action_type": a.action_type,
                    "operation_id": a.operation_id,
                    "payload_json": a.payload_json,
                    "state": a.state.value,
                    "attempt_count": a.attempt_count,
                    "created_at": a.created_at,
                    "updated_at": a.updated_at,
                    "last_error": a.last_error,
                    "recovery_note": a.recovery_note,
                }
            )

        _write_json(out / "task_spec.json", spec.model_dump(mode="json"))
        _write_json(out / "verification.json", result.to_dict())
        _write_json(
            out / "journal.json",
            {
                "run": {
                    "run_id": run.run_id,
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                    "state": run.state,
                    "goal_summary": run.goal_summary,
                    "finished_at": run.finished_at,
                },
                "actions": action_export,
            },
        )

        if progress_events is not None:
            lines = []
            for ev in progress_events:
                lines.append(
                    json.dumps(
                        {
                            "timestamp": ev.timestamp.isoformat(),
                            "run_state": ev.run_state.value,
                            "message": ev.message,
                            "candidate_id": ev.candidate_id,
                            "action": ev.action,
                            "event_type": ev.event_type,
                        },
                        sort_keys=True,
                        ensure_ascii=True,
                    )
                )
            (out / "progress.jsonl").write_text(
                ("\n".join(lines) + ("\n" if lines else "")),
                encoding="utf-8",
            )

        (out / "summary.md").write_text(
            _render_summary(result=result, spec=spec, journal_actions=action_export),
            encoding="utf-8",
        )

        artifacts: list[dict[str, Any]] = []
        for path in sorted(out.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "manifest.json":
                continue
            rel = path.relative_to(out).as_posix()
            artifacts.append(
                {
                    "path": rel,
                    "type": _artifact_type(rel),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        manifest = {
            "run_id": result.run_id,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "verification_status": result.overall_status.value,
            "verified_complete": result.verified_complete,
            "artifacts": artifacts,
            "hash_note": (
                "SHA-256 values provide integrity checking of package files; "
                "not cryptographic identity or signing. manifest.json is not self-hashed."
            ),
        }
        _write_json(out / "manifest.json", manifest)
        return out


def _artifact_type(rel: str) -> str:
    if rel.startswith("screenshots/"):
        return "screenshot"
    if rel.endswith(".json"):
        return "json"
    if rel.endswith(".jsonl"):
        return "progress"
    if rel.endswith(".md"):
        return "summary"
    return "file"


def validate_manifest_hashes(package_dir: Path) -> list[str]:
    """Return list of mismatch descriptions (empty if ok)."""
    manifest_path = package_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    for art in data.get("artifacts", []):
        path = package_dir / art["path"]
        if not path.is_file():
            mismatches.append(f"missing {art['path']}")
            continue
        digest = sha256_file(path)
        if digest != art["sha256"]:
            mismatches.append(f"hash mismatch {art['path']}")
        if path.stat().st_size != art["size_bytes"]:
            mismatches.append(f"size mismatch {art['path']}")
    return mismatches

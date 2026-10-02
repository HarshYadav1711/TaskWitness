"""Independent whole-goal verification types (Phase 6).

Deterministic. No LLM. Executor/journal success is not proof.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class CheckStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    incomplete = "incomplete"
    blocked = "blocked"


class OverallVerificationStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    incomplete = "incomplete"
    blocked = "blocked"


@dataclass
class PostconditionCheck:
    check_id: str
    description: str
    expected: str
    observed: str
    status: CheckStatus
    candidate_id: Optional[str] = None
    action: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "candidate_id": self.candidate_id,
            "action": self.action,
            "description": self.description,
            "expected": self.expected,
            "observed": self.observed,
            "status": self.status.value,
            "evidence_refs": list(self.evidence_refs),
            "note": self.note,
        }


@dataclass
class VerificationResult:
    run_id: str
    overall_status: OverallVerificationStatus
    verified_complete: bool
    checks: list[PostconditionCheck]
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    expected_candidate_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status.value,
            "verified_complete": self.verified_complete,
            "expected_candidate_ids": list(self.expected_candidate_ids),
            "checks": [c.to_dict() for c in self.checks],
            "counts": {
                "passed": sum(1 for c in self.checks if c.status is CheckStatus.passed),
                "failed": sum(1 for c in self.checks if c.status is CheckStatus.failed),
                "incomplete": sum(1 for c in self.checks if c.status is CheckStatus.incomplete),
                "blocked": sum(1 for c in self.checks if c.status is CheckStatus.blocked),
            },
        }


def aggregate_overall(checks: list[PostconditionCheck]) -> OverallVerificationStatus:
    if any(c.status is CheckStatus.failed for c in checks):
        return OverallVerificationStatus.failed
    if any(c.status is CheckStatus.blocked for c in checks):
        return OverallVerificationStatus.blocked
    if any(c.status is CheckStatus.incomplete for c in checks):
        return OverallVerificationStatus.incomplete
    return OverallVerificationStatus.passed

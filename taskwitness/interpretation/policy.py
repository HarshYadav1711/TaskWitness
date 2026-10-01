"""Controlled-environment policy for interpreted TaskSpecs."""

from __future__ import annotations

from pathlib import Path

from taskwitness.candidate_source import load_candidates
from taskwitness.schemas import ActionType, TaskSpec

# Must match TalentDesk pipeline stages used for stage changes.
PIPELINE_STAGES: frozenset[str] = frozenset(
    {
        "Applied",
        "Screening",
        "Shortlisted",
        "Interview Ready",
        "Interview Scheduled",
        "Closed",
    }
)

APPROVED_SOURCE = "data/candidates.csv"

_REPO_ROOT = Path(__file__).resolve().parents[2]


class PolicyRejection(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def approved_source_path() -> Path:
    return _REPO_ROOT / APPROVED_SOURCE


def supported_roles(source_file: Path | None = None) -> frozenset[str]:
    path = source_file or approved_source_path()
    return frozenset(c.role for c in load_candidates(path))


def supported_statuses(source_file: Path | None = None) -> frozenset[str]:
    path = source_file or approved_source_path()
    return frozenset(c.status for c in load_candidates(path))


def normalize_source_file(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def _source_is_unsafe(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    if ".." in stripped.replace("\\", "/"):
        return True
    if "://" in stripped:
        return True
    if stripped.startswith(("/", "\\")):
        return True
    # Windows drive / UNC
    if len(stripped) >= 2 and stripped[1] == ":":
        return True
    if stripped.startswith("\\\\"):
        return True
    if lowered.startswith("file:"):
        return True
    return False


def validate_taskspec_policy(spec: TaskSpec) -> TaskSpec:
    """Return a policy-approved TaskSpec or raise PolicyRejection."""
    if _source_is_unsafe(spec.source_file):
        raise PolicyRejection(
            f"unsafe source_file {spec.source_file!r}; only {APPROVED_SOURCE} is allowed"
        )

    source = normalize_source_file(spec.source_file)
    if source != APPROVED_SOURCE:
        raise PolicyRejection(
            f"unsupported source_file {spec.source_file!r}; only {APPROVED_SOURCE} is allowed"
        )

    roles = supported_roles()
    if spec.role not in roles:
        raise PolicyRejection(
            f"unsupported role {spec.role!r}; supported: {sorted(roles)}"
        )

    statuses = supported_statuses()
    if spec.candidate_status not in statuses:
        raise PolicyRejection(
            f"unsupported candidate_status {spec.candidate_status!r}; "
            f"supported: {sorted(statuses)}"
        )

    if ActionType.set_stage in spec.actions:
        if spec.target_stage not in PIPELINE_STAGES:
            raise PolicyRejection(
                f"unsupported target_stage {spec.target_stage!r}; "
                f"supported: {sorted(PIPELINE_STAGES)}"
            )

    return spec.model_copy(update={"source_file": APPROVED_SOURCE})

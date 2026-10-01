"""Read synthetic candidates from CSV — never from the demo database."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceCandidate:
    candidate_id: str
    name: str
    email: str
    role: str
    status: str
    current_stage: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name.strip() else self.name


def load_candidates(source_file: str | Path) -> list[SourceCandidate]:
    path = Path(source_file)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {
            "candidate_id",
            "name",
            "email",
            "role",
            "status",
            "current_stage",
        }
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"candidates CSV missing required columns: {required}")
        rows: list[SourceCandidate] = []
        for row in reader:
            rows.append(
                SourceCandidate(
                    candidate_id=row["candidate_id"].strip(),
                    name=row["name"].strip(),
                    email=row["email"].strip(),
                    role=row["role"].strip(),
                    status=row["status"].strip(),
                    current_stage=row["current_stage"].strip(),
                )
            )
        return rows


def filter_candidates(
    candidates: list[SourceCandidate],
    *,
    role: str,
    candidate_status: str,
) -> list[SourceCandidate]:
    """Exact role and status match (business values from the CSV)."""
    return [
        c
        for c in candidates
        if c.role == role and c.status == candidate_status
    ]

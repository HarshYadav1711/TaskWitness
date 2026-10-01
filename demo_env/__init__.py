"""Synthetic recruiting demo environment (TalentDesk + TeamMail).

This package hosts controlled business applications only.
It is not the TaskWitness operator, journal, or executor.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
DEFAULT_DB_PATH = REPO_ROOT / "demo_env" / "demo_env.sqlite3"
CANDIDATES_CSV = REPO_ROOT / "data" / "candidates.csv"

PIPELINE_STAGES = (
    "Applied",
    "Screening",
    "Shortlisted",
    "Interview Ready",
    "Interview Scheduled",
    "Closed",
)

# Stages present in seed CSV that may not be in the change UI list.
# Stored as-is on seed; stage changes must use PIPELINE_STAGES.

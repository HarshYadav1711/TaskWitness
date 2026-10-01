"""Seed and reset the synthetic demo environment.

Usage:
    python -m demo_env.seed --reset
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from demo_env import CANDIDATES_CSV, DEFAULT_DB_PATH
from demo_env.db import (
    clear_candidates,
    clear_fail_after_send,
    clear_messages,
    connect,
    init_db,
)


def load_candidates_from_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
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
        rows = []
        for row in reader:
            email = row["email"].strip()
            if not email.endswith("@example.test"):
                raise ValueError(f"non-synthetic email in seed data: {email}")
            rows.append(
                {
                    "candidate_id": row["candidate_id"].strip(),
                    "name": row["name"].strip(),
                    "email": email,
                    "role": row["role"].strip(),
                    "status": row["status"].strip(),
                    "current_stage": row["current_stage"].strip(),
                }
            )
        return rows


def reset_environment(
    *,
    db_path: Path | None = None,
    csv_path: Path | None = None,
) -> int:
    path = db_path or DEFAULT_DB_PATH
    source = csv_path or CANDIDATES_CSV
    candidates = load_candidates_from_csv(source)

    conn = connect(path)
    try:
        init_db(conn)
        clear_messages(conn)
        clear_candidates(conn)
        clear_fail_after_send(conn)
        conn.executemany(
            "INSERT INTO candidates "
            "(candidate_id, name, email, role, status, current_stage) "
            "VALUES (:candidate_id, :name, :email, :role, :status, :current_stage)",
            candidates,
        )
        conn.commit()
    finally:
        conn.close()
    return len(candidates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed/reset TalentDesk and TeamMail synthetic state."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Recreate candidates from CSV and clear TeamMail messages.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional SQLite path (defaults to demo_env/demo_env.sqlite3).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional candidates CSV path.",
    )
    args = parser.parse_args(argv)

    if not args.reset:
        parser.error("specify --reset")

    count = reset_environment(db_path=args.db, csv_path=args.csv)
    db = args.db or DEFAULT_DB_PATH
    print(f"Reset complete: {count} candidates loaded into {db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""CLI wrapper for TaskWitness Phase-8 assessment acceptance."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taskwitness.assessment_accept import main

if __name__ == "__main__":
    raise SystemExit(main())

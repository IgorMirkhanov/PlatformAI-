"""Repo-root wrapper: ``python scripts/make_superadmin.py --email ...``."""

from __future__ import annotations

import runpy
from pathlib import Path

_TARGET = Path(__file__).resolve().parents[1] / "backend" / "scripts" / "make_superadmin.py"
runpy.run_path(str(_TARGET), run_name="__main__")

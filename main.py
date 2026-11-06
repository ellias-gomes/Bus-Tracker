#!/usr/bin/env python3
"""Ponto de entrada do BusTracker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bustracker.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

"""Pytest configuration: make the project importable without an install and
provide small geometry helpers shared across tests."""

import os
import sys
from pathlib import Path

# Force Qt offscreen for the whole test session (must be set before any
# QApplication is created anywhere in the process).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ring_segments(pts):
    """Closed ring of points -> list of (p, q) edge segments."""
    n = len(pts)
    return [(pts[i], pts[(i + 1) % n]) for i in range(n)]

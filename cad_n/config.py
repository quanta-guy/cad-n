"""Application-wide constants and the global tolerance policy.

The tolerance policy is centralised here (doc section 7.2). Every geometry
operation must read its tolerances from a single :class:`Tolerances` instance
so behaviour is consistent and tunable from the advanced settings panel.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import __app_name__, __version__

APP_NAME = __app_name__
APP_VERSION = __version__


@dataclass
class Tolerances:
    """Global geometric tolerances, all in millimetres / degrees.

    Defaults match doc section 7.2 / the agent prompt.
    """

    snap_tolerance_mm: float = 0.05
    curve_chord_tolerance_mm: float = 0.1
    min_segment_length_mm: float = 0.05
    overlap_tolerance_mm: float = 0.01
    collinear_angle_tolerance_deg: float = 0.5
    # Parts smaller than this are treated as noise (arrowheads, fragments).
    # See doc section 18 ("many tiny triangles" prevention).
    min_part_area_mm2: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Tolerances":
        if not data:
            return cls()
        known = {f for f in cls().to_dict()}
        return cls(**{k: float(v) for k, v in data.items() if k in known})


# A module-level default that non-UI code can fall back to.
DEFAULT_TOLERANCES = Tolerances()

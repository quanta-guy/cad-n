"""Unit handling for DXF import (doc 7.1: "Units are missing or ambiguous").

DXF stores its drawing units in the ``$INSUNITS`` header variable as an integer
code. We convert every imported drawing to millimetres (the application's
internal unit) using the scale factors below.
"""

from __future__ import annotations

# DXF $INSUNITS code -> (scale factor to millimetres, human name).
# Source: the public DXF reference / ezdxf docs.
_INSUNITS_TO_MM: dict[int, tuple[float, str]] = {
    0: (1.0, "unitless"),       # assume mm, but caller should warn
    1: (25.4, "inches"),
    2: (304.8, "feet"),
    3: (1_609_344.0, "miles"),
    4: (1.0, "millimeters"),
    5: (10.0, "centimeters"),
    6: (1000.0, "meters"),
    7: (1_000_000.0, "kilometers"),
    8: (25.4e-6, "microinches"),
    9: (25.4e-3, "mils"),
    10: (914.4, "yards"),
    11: (1.0e-7, "angstroms"),
    12: (1.0e-6, "nanometers"),
    13: (1.0e-3, "microns"),
    14: (100.0, "decimeters"),
    15: (10_000.0, "decameters"),
    16: (100_000.0, "hectometers"),
    17: (1.0e12, "gigameters"),
    18: (1.495978707e14, "astronomical units"),
    19: (9.4607304725808e18, "light years"),
    20: (3.0856775814914e19, "parsecs"),
}


def insunits_to_mm(code: int | None) -> tuple[float, str, bool]:
    """Return ``(scale_to_mm, unit_name, is_ambiguous)`` for a DXF INSUNITS code.

    ``is_ambiguous`` is True when the drawing declares no real units (code 0 or
    unknown), in which case we fall back to millimetres but the importer should
    raise an operator warning.
    """
    if code is None:
        return 1.0, "unspecified", True
    scale, name = _INSUNITS_TO_MM.get(int(code), (1.0, "unknown"))
    ambiguous = int(code) == 0 or name == "unknown"
    return scale, name, ambiguous

"""Core domain models (doc section 9.3).

Geometry is represented with Shapely ``Polygon`` objects: the polygon exterior
is the outer cut contour and its interiors are holes. We keep the models mostly
"plain data" with light helpers, and provide ``to_dict`` / ``from_dict`` for the
JSON job format (doc 7.7).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


# --------------------------------------------------------------------------- #
# Notices (operator-facing warnings) -- doc 12.3 "log both, show one".
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Notice:
    """A single plain-English message for the operator.

    ``message`` is what the operator sees; ``detail`` carries developer context
    that is logged but not shown prominently.
    """

    message: str
    severity: Severity = Severity.WARNING
    code: str = ""
    part_name: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "severity": self.severity.value,
            "code": self.code,
            "part_name": self.part_name,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Notice":
        return cls(
            message=d.get("message", ""),
            severity=Severity(d.get("severity", "warning")),
            code=d.get("code", ""),
            part_name=d.get("part_name"),
            detail=d.get("detail", ""),
        )


class PlacementStrategy(str, Enum):
    """Part ordering heuristics for placement (doc 7.5)."""

    AREA_DESC = "area_desc"           # largest area first
    LONGEST_SIDE = "longest_side"     # longest bounding-box side first
    HEIGHT_DESC = "height_desc"       # tallest bounding box first
    RANDOM = "random"                 # shuffled (used by multi-seed search)


def _coords_of(ring) -> list[tuple[float, float]]:
    """Return ring coordinates as plain (x, y) tuples without the closing dup."""
    pts = [(float(x), float(y)) for x, y in ring.coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


# --------------------------------------------------------------------------- #
# Part
# --------------------------------------------------------------------------- #
@dataclass
class Part:
    """A single distinct part geometry plus how many to nest.

    ``geom`` is the canonical Shapely polygon (exterior = outer contour,
    interiors = holes). ``allowed_rotations`` of ``None`` means "use the rotation
    step from the nesting settings"; an explicit list restricts rotations for
    this part only.
    """

    name: str
    geom: Polygon
    quantity: int = 1
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    source_file: Optional[str] = None
    allowed_rotations: Optional[list[float]] = None
    allow_mirror: bool = False
    material: Optional[str] = None
    thickness: Optional[float] = None
    metadata: dict = field(default_factory=dict)
    notices: list[Notice] = field(default_factory=list)
    # Open cut geometry that lies inside this part's outer boundary: micro-joints,
    # chase outlines and other internal cut lines drawn as open (non-closing)
    # segments. These never drive nesting (the outer boundary does) -- they are
    # kept verbatim, transformed with the part, and re-emitted on the CUT layer at
    # export. Each entry is one open polyline as a list of (x, y) points in the
    # part's own coordinate frame (the same frame as ``geom``).
    internal_paths: list[list[tuple[float, float]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalise winding: exterior CCW, holes CW. Makes downstream area and
        # offset operations predictable.
        if self.geom is not None and not self.geom.is_empty:
            self.geom = orient(self.geom, sign=1.0)

    # -- geometry helpers --------------------------------------------------- #
    @property
    def outer_polygon(self) -> list[tuple[float, float]]:
        return _coords_of(self.geom.exterior)

    @property
    def holes(self) -> list[list[tuple[float, float]]]:
        return [_coords_of(r) for r in self.geom.interiors]

    @property
    def area(self) -> float:
        """Net area (holes subtracted)."""
        return float(self.geom.area)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(minx, miny, maxx, maxy)."""
        return tuple(float(v) for v in self.geom.bounds)  # type: ignore[return-value]

    @property
    def width(self) -> float:
        minx, _, maxx, _ = self.bounds
        return maxx - minx

    @property
    def height(self) -> float:
        _, miny, _, maxy = self.bounds
        return maxy - miny

    @property
    def has_error(self) -> bool:
        return any(n.severity is Severity.ERROR for n in self.notices)

    # -- factories ---------------------------------------------------------- #
    @classmethod
    def from_rings(
        cls,
        name: str,
        outer: list[tuple[float, float]],
        holes: Optional[list[list[tuple[float, float]]]] = None,
        **kwargs,
    ) -> "Part":
        poly = Polygon(outer, holes or [])
        return cls(name=name, geom=poly, **kwargs)

    # -- serialisation ------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity,
            "source_file": self.source_file,
            "outer": self.outer_polygon,
            "holes": self.holes,
            "allowed_rotations": self.allowed_rotations,
            "allow_mirror": self.allow_mirror,
            "material": self.material,
            "thickness": self.thickness,
            "metadata": self.metadata,
            "internal_paths": [
                [[float(x), float(y)] for x, y in path] for path in self.internal_paths
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Part":
        part = cls.from_rings(
            name=d["name"],
            outer=[tuple(p) for p in d["outer"]],
            holes=[[tuple(p) for p in h] for h in d.get("holes", [])],
            quantity=int(d.get("quantity", 1)),
            source_file=d.get("source_file"),
            allowed_rotations=d.get("allowed_rotations"),
            allow_mirror=bool(d.get("allow_mirror", False)),
            material=d.get("material"),
            thickness=d.get("thickness"),
            metadata=d.get("metadata", {}),
            internal_paths=[
                [tuple(pt) for pt in path] for path in d.get("internal_paths", [])
            ],
        )
        part.id = d.get("id", part.id)
        return part


def make_rectangle_part(
    name: str,
    length_mm: float,
    width_mm: float,
    quantity: int = 1,
    allow_rotation: bool = True,
    **kwargs,
) -> Part:
    """Manual rectangular part (doc 7.3). Length is along X, width along Y."""
    if length_mm <= 0 or width_mm <= 0:
        raise ValueError("Rectangle length and width must be positive.")
    outer = [(0.0, 0.0), (length_mm, 0.0), (length_mm, width_mm), (0.0, width_mm)]
    rotations = [0.0, 90.0] if allow_rotation else [0.0]
    return Part.from_rings(
        name, outer, holes=None, quantity=quantity, allowed_rotations=rotations, **kwargs
    )


# --------------------------------------------------------------------------- #
# Sheet
# --------------------------------------------------------------------------- #
@dataclass
class Sheet:
    """Sheet stock. MVP supports rectangles; ``boundary_polygon`` allows a
    non-rectangular boundary later (doc 10.5)."""

    name: str
    width_mm: float          # X extent (length)
    height_mm: float         # Y extent (width)
    quantity_available: int = 1_000_000  # effectively unlimited by default
    margin_mm: float = 0.0
    material: Optional[str] = None
    thickness: Optional[float] = None
    boundary_polygon: Optional[Polygon] = None

    @property
    def usable_width(self) -> float:
        return max(0.0, self.width_mm - 2 * self.margin_mm)

    @property
    def usable_height(self) -> float:
        return max(0.0, self.height_mm - 2 * self.margin_mm)

    @property
    def usable_area(self) -> float:
        """Usable area (doc 13.1). Uses boundary polygon if present."""
        if self.boundary_polygon is not None and not self.boundary_polygon.is_empty:
            return float(self.boundary_polygon.area)
        return self.usable_width * self.usable_height

    def usable_rect(self) -> tuple[float, float, float, float]:
        """Inset placement rectangle (minx, miny, maxx, maxy)."""
        return (
            self.margin_mm,
            self.margin_mm,
            self.width_mm - self.margin_mm,
            self.height_mm - self.margin_mm,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "quantity_available": self.quantity_available,
            "margin_mm": self.margin_mm,
            "material": self.material,
            "thickness": self.thickness,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Sheet":
        return cls(
            name=d.get("name", "Sheet"),
            width_mm=float(d["width_mm"]),
            height_mm=float(d["height_mm"]),
            quantity_available=int(d.get("quantity_available", 1_000_000)),
            margin_mm=float(d.get("margin_mm", 0.0)),
            material=d.get("material"),
            thickness=d.get("thickness"),
        )


# --------------------------------------------------------------------------- #
# Nesting settings
# --------------------------------------------------------------------------- #
@dataclass
class NestingSettings:
    part_spacing_mm: float = 2.0
    kerf_mm: float = 0.0
    rotation_step_deg: float = 90.0      # 0 disables rotation
    time_limit_sec: float = 20.0
    attempt_count: int = 4
    placement_strategy: PlacementStrategy = PlacementStrategy.AREA_DESC
    allow_part_in_part: bool = False     # later (doc 10.4)
    allow_common_cut: bool = False       # later (doc 10.3)
    random_seed: int = 12345
    grid_step_mm: float = 0.0            # 0 = auto (1/4 of smallest part edge)

    @property
    def clearance_mm(self) -> float:
        """Total gap to enforce between part edges = spacing + kerf."""
        return max(0.0, self.part_spacing_mm) + max(0.0, self.kerf_mm)

    def rotations_for(self, part: Part) -> list[float]:
        """Resolve the list of rotation angles to try for ``part``."""
        if part.allowed_rotations is not None:
            return list(dict.fromkeys(float(a) % 360.0 for a in part.allowed_rotations))
        step = self.rotation_step_deg
        if step <= 0:
            return [0.0]
        angles = []
        a = 0.0
        while a < 360.0 - 1e-9:
            angles.append(round(a, 6))
            a += step
        return angles or [0.0]

    def to_dict(self) -> dict:
        return {
            "part_spacing_mm": self.part_spacing_mm,
            "kerf_mm": self.kerf_mm,
            "rotation_step_deg": self.rotation_step_deg,
            "time_limit_sec": self.time_limit_sec,
            "attempt_count": self.attempt_count,
            "placement_strategy": self.placement_strategy.value,
            "allow_part_in_part": self.allow_part_in_part,
            "allow_common_cut": self.allow_common_cut,
            "random_seed": self.random_seed,
            "grid_step_mm": self.grid_step_mm,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "NestingSettings":
        if not d:
            return cls()
        return cls(
            part_spacing_mm=float(d.get("part_spacing_mm", 2.0)),
            kerf_mm=float(d.get("kerf_mm", 0.0)),
            rotation_step_deg=float(d.get("rotation_step_deg", 90.0)),
            time_limit_sec=float(d.get("time_limit_sec", 20.0)),
            attempt_count=int(d.get("attempt_count", 4)),
            placement_strategy=PlacementStrategy(d.get("placement_strategy", "area_desc")),
            allow_part_in_part=bool(d.get("allow_part_in_part", False)),
            allow_common_cut=bool(d.get("allow_common_cut", False)),
            random_seed=int(d.get("random_seed", 12345)),
            grid_step_mm=float(d.get("grid_step_mm", 0.0)),
        )


# --------------------------------------------------------------------------- #
# Placement + result
# --------------------------------------------------------------------------- #
@dataclass
class Placement:
    """A concrete placement of one part instance on one sheet."""

    part_id: str
    part_name: str
    sheet_index: int          # which physical sheet (0-based)
    x_mm: float
    y_mm: float
    rotation_deg: float
    mirrored: bool
    polygon_world: Polygon    # final placed geometry in sheet coordinates
    # Preserved internal cut lines (micro-joints / chase outlines) placed in the
    # same sheet coordinates as ``polygon_world``. Each is a Shapely LineString.
    internal_world: list = field(default_factory=list)

    @property
    def area(self) -> float:
        return float(self.polygon_world.area)


@dataclass
class UnnestedPart:
    part_id: str
    part_name: str
    quantity_failed: int
    reason: str = ""


@dataclass
class NestingResult:
    placements: list[Placement] = field(default_factory=list)
    unnested_parts: list[UnnestedPart] = field(default_factory=list)
    sheet: Optional[Sheet] = None
    # Sheet stock used for each physical sheet index. For a single stock type
    # this is just that sheet repeated; with multiple stock sizes the entries
    # differ. Empty on results built before multi-stock support (see sheet_at).
    sheets: list[Sheet] = field(default_factory=list)
    sheet_count_used: int = 0
    utilization_by_sheet: list[float] = field(default_factory=list)
    total_utilization: float = 0.0
    used_length_by_sheet: list[float] = field(default_factory=list)
    remnant_length_by_sheet: list[float] = field(default_factory=list)
    # Ranked alternative stock-mix configurations to choose from (multi-stock
    # only); element 0 is the one this result represents. Empty for single stock.
    configurations: list["ConfigOption"] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    runtime_sec: float = 0.0

    @property
    def total_parts_nested(self) -> int:
        return len(self.placements)

    @property
    def total_parts_failed(self) -> int:
        return sum(u.quantity_failed for u in self.unnested_parts)

    def placements_on(self, sheet_index: int) -> list[Placement]:
        return [p for p in self.placements if p.sheet_index == sheet_index]

    def sheet_at(self, index: int) -> Optional[Sheet]:
        """Sheet stock for physical sheet ``index``; falls back to the single
        ``sheet`` for results built before multi-stock support."""
        if 0 <= index < len(self.sheets):
            return self.sheets[index]
        return self.sheet


@dataclass
class ConfigOption:
    """One evaluated stock-mix configuration the operator can pick from.

    ``counts`` is the realised usage as ``(sheet type name, number used)`` pairs.
    ``stock_area`` (total purchased sheet area) is the objective we minimise.
    """

    label: str
    counts: list[tuple[str, int]]
    stock_area: float
    waste_area: float
    utilization: float
    sheets_used: int
    all_placed: bool
    parts_failed: int = 0
    result: Optional[NestingResult] = None

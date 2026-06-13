"""Placement primitives: prepare rotated/clearance-inflated part variants and
run one bottom-left-fill (BLF) packing attempt (doc 10.1).

Correctness rules that must always hold (doc 'agent prompt' acceptance):
  * a placed part lies fully inside the sheet's usable rectangle;
  * inflating a candidate by the full clearance and testing against already
    placed *originals* guarantees >= clearance between every pair of parts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from shapely import STRtree
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, Polygon

from .models import NestingSettings, Part, Placement, Sheet

_AREA_EPS = 1e-6
_FIT_EPS = 1e-6


@dataclass
class Variant:
    angle: float
    mirrored: bool
    base: Polygon          # rotated/mirrored, anchored at its own bbox-min = origin
    infl: Polygon          # base inflated by clearance (for overlap tests)
    w: float
    h: float
    area: float
    # Internal cut lines (micro-joints / chase outlines) carried through the same
    # mirror+rotate+anchor transform as ``base`` so they stay registered to it.
    internal: list = field(default_factory=list)  # list[LineString]


@dataclass
class PreparedPart:
    part: Part
    variants: list[Variant]
    area: float
    sort_key: float


def prepare_part(part: Part, settings: NestingSettings) -> PreparedPart:
    clearance = settings.clearance_mm
    variants: list[Variant] = []
    mirrors = [False, True] if part.allow_mirror else [False]
    seen: set[tuple] = set()
    base_internal = [LineString(p) for p in part.internal_paths if len(p) >= 2]
    for mirror in mirrors:
        for angle in settings.rotations_for(part):
            g = part.geom
            ig = base_internal
            if mirror:
                g = scale(g, xfact=-1.0, yfact=1.0, origin=(0, 0))
                ig = [scale(l, xfact=-1.0, yfact=1.0, origin=(0, 0)) for l in ig]
            if angle:
                g = rotate(g, angle, origin=(0, 0))
                ig = [rotate(l, angle, origin=(0, 0)) for l in ig]
            # Anchor the boundary at the origin and shift the internal lines by the
            # identical offset so they stay registered to it.
            minx, miny, _, _ = g.bounds
            g = translate(g, -minx, -miny)
            ig = [translate(l, -minx, -miny) for l in ig]
            gx0, gy0, gx1, gy1 = g.bounds
            # Skip rotations that produce a duplicate footprint+shape.
            sig = (round(gx1, 4), round(gy1, 4), round(g.area, 4),
                   round(g.centroid.x, 3), round(g.centroid.y, 3))
            if sig in seen:
                continue
            seen.add(sig)
            infl = (
                g.buffer(clearance, join_style="mitre", mitre_limit=3.0)
                if clearance > 0
                else g
            )
            variants.append(
                Variant(angle, mirror, g, infl, gx1 - gx0, gy1 - gy0, g.area,
                        internal=ig)
            )
    area = part.area
    return PreparedPart(part=part, variants=variants, area=area, sort_key=area)


class SheetState:
    """Tracks placed originals on one physical sheet and answers placement
    queries with a BLF heuristic."""

    def __init__(self, sheet, settings: NestingSettings) -> None:
        self.sheet = sheet
        self.settings = settings
        self.minx, self.miny, self.maxx, self.maxy = sheet.usable_rect()
        self.placed_polys: list[Polygon] = []      # original (un-inflated)
        self.placed_infl_bounds: list[tuple] = []   # bounds of inflated polys
        self._tree: Optional[STRtree] = None

    @property
    def usable_w(self) -> float:
        return self.maxx - self.minx

    @property
    def usable_h(self) -> float:
        return self.maxy - self.miny

    def _rebuild_tree(self) -> None:
        self._tree = STRtree(self.placed_polys) if self.placed_polys else None

    def _overlaps(self, infl: Polygon) -> bool:
        if self._tree is None:
            return False
        for idx in self._tree.query(infl):
            other = self.placed_polys[int(idx)]
            inter = infl.intersection(other)
            if (not inter.is_empty) and inter.area > _AREA_EPS:
                return True
        return False

    def best_placement(self, variants: list[Variant]):
        """Return (y, x, variant, placed_base, placed_infl) for the lowest-then-
        leftmost feasible placement, or None."""
        best = None
        for v in variants:
            if v.w > self.usable_w + _FIT_EPS or v.h > self.usable_h + _FIT_EPS:
                continue
            # Candidate x columns: left margin + right edges of placed parts.
            xs = {self.minx}
            for (bminx, bminy, bmaxx, bmaxy) in self.placed_infl_bounds:
                if bmaxx + v.w <= self.maxx + _FIT_EPS:
                    xs.add(bmaxx)
            for x in sorted(xs):
                if x + v.w > self.maxx + _FIT_EPS:
                    continue
                # Candidate y rows at this x: bottom margin + tops of parts whose
                # x-band overlaps [x, x+w].
                ys = {self.miny}
                x_hi = x + v.w
                for (bminx, bminy, bmaxx, bmaxy) in self.placed_infl_bounds:
                    if bmaxx > x + _FIT_EPS and bminx < x_hi - _FIT_EPS:
                        ys.add(bmaxy)
                for y in sorted(ys):
                    if y + v.h > self.maxy + _FIT_EPS:
                        continue
                    dx, dy = x, y  # base is anchored at origin
                    placed_base = translate(v.base, dx, dy)
                    placed_infl = translate(v.infl, dx, dy)
                    if self._overlaps(placed_infl):
                        continue
                    cand = (y, x, v, placed_base, placed_infl)
                    if best is None or (y, x) < (best[0], best[1]):
                        best = cand
                    break  # lowest y for this column found
        return best

    def add(self, placed_base: Polygon, placed_infl: Polygon) -> None:
        self.placed_polys.append(placed_base)
        self.placed_infl_bounds.append(tuple(placed_infl.bounds))
        self._rebuild_tree()


@dataclass
class AttemptResult:
    placements: list[Placement] = field(default_factory=list)
    # part_id -> number of instances that could not be placed
    failed: dict[str, int] = field(default_factory=dict)
    sheets_used: int = 0
    # Sheet stock for each used physical sheet index (parallel to sheet_index).
    sheets: list[Sheet] = field(default_factory=list)


def run_attempt(
    prepared: list[PreparedPart],
    instance_order: list[int],
    bins: list[Sheet],
    settings: NestingSettings,
    open_until_fit: bool = False,
) -> AttemptResult:
    """One packing attempt into an ordered list of sheet ``bins``.

    ``instance_order`` indexes a flat instance list (parts expanded by quantity).
    Each part is placed bottom-left first-fit on an already-open sheet if it
    fits; otherwise bins are opened in order. With ``open_until_fit`` (used for
    mixed stock sizes) successive bins are opened until one accepts the part — a
    bin it does not fit stays open for later parts, so a part that only fits a
    later/larger bin still finds it. Without it (a single stock size) only the
    next fresh sheet is tried: if the part does not fit an empty sheet it is
    genuinely too large, matching the original fast single-stock behaviour.

    Only bins that receive a part count as used; placements are re-indexed onto
    that compacted set, and :attr:`AttemptResult.sheets` records the stock used.
    """
    instances: list[PreparedPart] = []
    for pp in prepared:
        instances.extend([pp] * pp.part.quantity)
    if not instance_order:
        instance_order = list(range(len(instances)))

    states: list[SheetState] = []
    state_sheet: list[Sheet] = []
    placements: list[Placement] = []
    result = AttemptResult()
    next_idx = 0
    n_bins = len(bins)

    def _place(st: SheetState, s_i: int, pp: PreparedPart, best) -> None:
        y, x, v, pbase, pinfl = best
        st.add(pbase, pinfl)
        internal_world = [translate(line, x, y) for line in v.internal]
        placements.append(Placement(
            part_id=pp.part.id, part_name=pp.part.name, sheet_index=s_i,
            x_mm=x, y_mm=y, rotation_deg=v.angle, mirrored=v.mirrored,
            polygon_world=pbase, internal_world=internal_world))

    for inst_idx in instance_order:
        pp = instances[inst_idx]
        placed = False
        for s_i, st in enumerate(states):
            best = st.best_placement(pp.variants)
            if best is not None:
                _place(st, s_i, pp, best)
                placed = True
                break
        if placed:
            continue

        if open_until_fit:
            # Open successive bins until one accepts the part; unfit bins stay
            # open (empty) for later parts.
            while next_idx < n_bins:
                sh = bins[next_idx]
                next_idx += 1
                st = SheetState(sh, settings)
                states.append(st)
                state_sheet.append(sh)
                best = st.best_placement(pp.variants)
                if best is not None:
                    _place(st, len(states) - 1, pp, best)
                    placed = True
                    break
        elif next_idx < n_bins:
            # Single stock size: try one fresh sheet; if it does not fit, the
            # part is too large (do not consume the bin).
            sh = bins[next_idx]
            st = SheetState(sh, settings)
            best = st.best_placement(pp.variants)
            if best is not None:
                next_idx += 1
                states.append(st)
                state_sheet.append(sh)
                _place(st, len(states) - 1, pp, best)
                placed = True

        if not placed:
            result.failed[pp.part.id] = result.failed.get(pp.part.id, 0) + 1

    # Keep only sheets that received parts, preserving order; re-index.
    used_old = sorted({pl.sheet_index for pl in placements})
    remap = {old: new for new, old in enumerate(used_old)}
    for pl in placements:
        pl.sheet_index = remap[pl.sheet_index]
    result.placements = placements
    result.sheets = [state_sheet[old] for old in used_old]
    result.sheets_used = len(used_old)
    return result

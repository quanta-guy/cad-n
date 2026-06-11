"""Geometry cleaning and contour reconstruction (doc 7.2, 11.4).

The importer hands us two kinds of geometry:

* ``closed_rings`` -- contours that came from a single closed entity
  (closed LWPOLYLINE/POLYLINE, CIRCLE, full ELLIPSE). We trust their vertex
  order and only tidy them.
* ``open_segments`` -- loose line segments (LINE, ARC, open polylines, flattened
  splines). These must be *stitched* back into closed loops.

We then classify every loop by containment (even-odd rule) to decide which loops
are outer part boundaries and which are holes, and emit plain-English notices for
anything suspicious (open contours, tiny fragments, self-intersections).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

from ..config import DEFAULT_TOLERANCES, Tolerances
from .models import Notice, Severity

Point = tuple[float, float]
Segment = tuple[Point, Point]


# Determined empirically (see test_geometry_cleaner): with the "clockwise-most
# next half-edge" rule below, the bounded interior faces come out with POSITIVE
# signed area while the single unbounded outer face per component is negative.
_BOUNDED_FACE_SIGN = 1.0


@dataclass
class CleanResult:
    polygons: list[Polygon] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    open_chain_count: int = 0
    duplicate_segment_count: int = 0
    tiny_segment_count: int = 0


# --------------------------------------------------------------------------- #
# Point welding (endpoint snapping) -- doc 7.2.
# --------------------------------------------------------------------------- #
class PointWeld:
    """Snap points that fall within ``tol`` of each other to a shared index.

    Uses a spatial hash with cell size = ``tol`` and checks the 9 neighbouring
    cells, so points that straddle a grid boundary still weld correctly.
    """

    def __init__(self, tol: float) -> None:
        self.tol = max(tol, 1e-9)
        self.cell = self.tol
        self.points: list[Point] = []
        self._buckets: dict[tuple[int, int], list[int]] = {}

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))

    def weld(self, x: float, y: float) -> int:
        cx, cy = self._key(x, y)
        best_i = -1
        best_d2 = self.tol * self.tol
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for i in self._buckets.get((gx, gy), ()):  # type: ignore[arg-type]
                    px, py = self.points[i]
                    d2 = (px - x) ** 2 + (py - y) ** 2
                    if d2 <= best_d2:
                        best_d2 = d2
                        best_i = i
        if best_i >= 0:
            return best_i
        idx = len(self.points)
        self.points.append((x, y))
        self._buckets.setdefault((cx, cy), []).append(idx)
        return idx


# --------------------------------------------------------------------------- #
# Graph helpers
# --------------------------------------------------------------------------- #
def _connected_components(adj: dict[int, set[int]]) -> list[set[int]]:
    seen: set[int] = set()
    comps: list[set[int]] = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]
        comp: set[int] = set()
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.add(n)
            stack.extend(adj[n] - seen)
        comps.append(comp)
    return comps


def _prune_leaves(adj: dict[int, set[int]], nodes: set[int]) -> bool:
    """Iteratively remove degree<=1 nodes within ``nodes``. Returns True if any
    dangling (open) edge was pruned."""
    pruned = False
    changed = True
    while changed:
        changed = False
        for n in list(nodes):
            if n in nodes and len(adj[n] & nodes) <= 1:
                neigh = adj[n] & nodes
                for m in neigh:
                    adj[m].discard(n)
                adj[n].clear()
                nodes.discard(n)
                pruned = True
                changed = True
    return pruned


def _walk_simple_cycle(adj: dict[int, set[int]], nodes: set[int]) -> list[int] | None:
    """Walk a connected component where every node has degree exactly 2."""
    if not nodes:
        return None
    for n in nodes:
        if len(adj[n] & nodes) != 2:
            return None
    start = next(iter(nodes))
    loop = [start]
    prev = None
    cur = start
    while True:
        nbrs = list(adj[cur] & nodes)
        nxt = nbrs[0] if nbrs[0] != prev else nbrs[1]
        if nxt == start:
            break
        if nxt in loop:  # safety against tangled input
            break
        loop.append(nxt)
        prev, cur = cur, nxt
        if len(loop) > len(nodes) + 1:
            break
    return loop if len(loop) >= 3 else None


def _signed_area(pts: list[Point]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def _dcel_faces(
    points: list[Point], adj: dict[int, set[int]], nodes: set[int]
) -> list[list[int]]:
    """Extract minimal bounded faces from a branched planar component using the
    angular "clockwise-most next half-edge" rule. Handles loops that share
    vertices/edges (e.g. common-cut style adjacency)."""
    # CCW-sorted neighbour order per node.
    order: dict[int, list[int]] = {}
    pos: dict[int, dict[int, int]] = {}
    for n in nodes:
        nbrs = sorted(
            adj[n] & nodes,
            key=lambda m, nn=n: math.atan2(
                points[m][1] - points[nn][1], points[m][0] - points[nn][0]
            ),
        )
        order[n] = nbrs
        pos[n] = {m: i for i, m in enumerate(nbrs)}

    visited: set[tuple[int, int]] = set()
    faces: list[list[int]] = []
    for u in nodes:
        for v in order[u]:
            if (u, v) in visited:
                continue
            face: list[int] = []
            cu, cv = u, v
            while (cu, cv) not in visited:
                visited.add((cu, cv))
                face.append(cu)
                # next half-edge: at cv, neighbour clockwise-adjacent to cu.
                deg = len(order[cv])
                i = pos[cv][cu]
                w = order[cv][(i - 1) % deg]
                cu, cv = cv, w
            if len(face) >= 3:
                faces.append(face)

    bounded: list[list[int]] = []
    for f in faces:
        pts = [points[i] for i in f]
        if _signed_area(pts) * _BOUNDED_FACE_SIGN > 1e-9:
            bounded.append(f)
    return bounded


# --------------------------------------------------------------------------- #
# Collinear merge + validation
# --------------------------------------------------------------------------- #
def merge_collinear(coords: list[Point], angle_tol_deg: float) -> list[Point]:
    """Drop vertices whose incoming/outgoing segments are nearly collinear."""
    if len(coords) < 3:
        return coords
    tol = math.radians(angle_tol_deg)
    out = list(coords)
    changed = True
    while changed and len(out) >= 3:
        changed = False
        n = len(out)
        keep = [True] * n
        for i in range(n):
            a = out[(i - 1) % n]
            b = out[i]
            c = out[(i + 1) % n]
            v1 = (b[0] - a[0], b[1] - a[1])
            v2 = (c[0] - b[0], c[1] - b[1])
            l1 = math.hypot(*v1)
            l2 = math.hypot(*v2)
            if l1 < 1e-12 or l2 < 1e-12:
                keep[i] = False
                changed = True
                continue
            cross = v1[0] * v2[1] - v1[1] * v2[0]
            dot = v1[0] * v2[0] + v1[1] * v2[1]
            angle = abs(math.atan2(cross, dot))
            if angle < tol:
                keep[i] = False
                changed = True
        new = [p for p, k in zip(out, keep) if k]
        # Avoid removing two adjacent vertices in one pass causing distortion:
        if len(new) >= 3:
            out = new
        else:
            break
    return out


def validate_and_repair(poly: Polygon, tol: Tolerances) -> tuple[Polygon | None, list[Notice]]:
    """Return a valid polygon (repaired if needed) or None, plus notices."""
    notices: list[Notice] = []
    if poly.is_empty or poly.area < tol.min_part_area_mm2:
        return None, notices
    if poly.is_valid:
        return orient(poly, 1.0), notices

    repaired = make_valid(poly)
    candidate: Polygon | None = None
    if isinstance(repaired, Polygon):
        candidate = repaired
    elif isinstance(repaired, MultiPolygon) and len(repaired.geoms) > 0:
        candidate = max(repaired.geoms, key=lambda g: g.area)
        notices.append(
            Notice(
                "A contour self-intersected and was repaired into the largest valid region.",
                Severity.WARNING,
                code="SELF_INTERSECTION_REPAIRED",
            )
        )
    if candidate is None or candidate.is_empty or candidate.area < tol.min_part_area_mm2:
        notices.append(
            Notice(
                "A contour could not be repaired into a valid part and was skipped.",
                Severity.ERROR,
                code="UNREPAIRABLE",
            )
        )
        return None, notices
    return orient(candidate, 1.0), notices


# --------------------------------------------------------------------------- #
# Loop extraction from open segments
# --------------------------------------------------------------------------- #
def stitch_loops(
    segments: list[Segment], tol: Tolerances
) -> tuple[list[list[Point]], int, int, int]:
    """Stitch loose segments into closed loops.

    Returns ``(loops, open_chain_count, duplicate_count, tiny_count)`` where each
    loop is a list of (x, y) coordinates (not closed)."""
    weld = PointWeld(tol.snap_tolerance_mm)
    edge_set: set[tuple[int, int]] = set()
    tiny = 0
    dup = 0
    for (x1, y1), (x2, y2) in segments:
        if math.hypot(x2 - x1, y2 - y1) < tol.min_segment_length_mm:
            tiny += 1
            continue
        a = weld.weld(x1, y1)
        b = weld.weld(x2, y2)
        if a == b:
            tiny += 1
            continue
        key = (a, b) if a < b else (b, a)
        if key in edge_set:
            dup += 1
            continue
        edge_set.add(key)

    adj: dict[int, set[int]] = {}
    for a, b in edge_set:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    loops: list[list[int]] = []
    open_chains = 0
    for comp in _connected_components(adj):
        comp = set(comp)
        had_leaf = _prune_leaves(adj, comp)
        if had_leaf:
            open_chains += 1
        if not comp:
            continue
        degrees = {n: len(adj[n] & comp) for n in comp}
        if all(d == 2 for d in degrees.values()):
            cyc = _walk_simple_cycle(adj, comp)
            if cyc:
                loops.append(cyc)
        else:
            loops.extend(_dcel_faces(weld.points, adj, comp))

    coord_loops = [[weld.points[i] for i in loop] for loop in loops]
    return coord_loops, open_chains, dup, tiny


# --------------------------------------------------------------------------- #
# Containment classification (even-odd) -- doc 11.4 step 5.
# --------------------------------------------------------------------------- #
def classify_containment(rings: list[Polygon]) -> list[Polygon]:
    """Given simple rings (no holes), build polygons assigning holes by the
    even-odd containment rule. Even depth -> solid part; odd depth -> hole."""
    items = [(i, p) for i, p in enumerate(rings) if not p.is_empty and p.area > 0]
    items.sort(key=lambda t: t[1].area)  # smallest first -> immediate parent search
    reps = {i: p.representative_point() for i, p in items}

    parent: dict[int, int | None] = {}
    for idx, (i, p) in enumerate(items):
        parent[i] = None
        # Smallest-area container that strictly contains rep point of i.
        for j, q in items[idx + 1 :]:
            if q.contains(reps[i]):
                parent[i] = j
                break

    def depth(i: int) -> int:
        d = 0
        cur = parent[i]
        guard = 0
        while cur is not None and guard < 10_000:
            d += 1
            cur = parent[cur]
            guard += 1
        return d

    depths = {i: depth(i) for i, _ in items}
    ring_by_idx = {i: p for i, p in items}

    polygons: list[Polygon] = []
    for i, p in items:
        if depths[i] % 2 == 0:  # solid
            holes = [
                list(ring_by_idx[j].exterior.coords)
                for j in depths
                if parent[j] == i and depths[j] % 2 == 1
            ]
            poly = Polygon(p.exterior.coords, holes)
            polygons.append(poly)
    return polygons


# --------------------------------------------------------------------------- #
# Top-level entry point
# --------------------------------------------------------------------------- #
def build_polygons(
    closed_rings: list[list[Point]],
    open_segments: list[Segment],
    tol: Tolerances | None = None,
) -> CleanResult:
    """Turn raw imported geometry into clean, valid polygons with holes."""
    tol = tol or DEFAULT_TOLERANCES
    result = CleanResult()

    candidate_rings: list[Polygon] = []

    # 1) Trust closed entity rings; just tidy them.
    for ring in closed_rings:
        coords = merge_collinear(list(ring), tol.collinear_angle_tolerance_deg)
        if len(coords) < 3:
            result.tiny_segment_count += 1
            continue
        try:
            poly = Polygon(coords)
        except Exception:
            continue
        if poly.is_empty:
            continue
        candidate_rings.append(Polygon(poly.exterior.coords))

    # 2) Stitch loose segments into loops.
    loops, open_chains, dup, tiny = stitch_loops(open_segments, tol)
    result.open_chain_count = open_chains
    result.duplicate_segment_count = dup
    result.tiny_segment_count += tiny
    for loop in loops:
        coords = merge_collinear(loop, tol.collinear_angle_tolerance_deg)
        if len(coords) < 3:
            continue
        try:
            poly = Polygon(coords)
        except Exception:
            continue
        if not poly.is_empty:
            candidate_rings.append(Polygon(poly.exterior.coords))

    if dup:
        result.notices.append(
            Notice(
                f"{dup} duplicate segment(s) removed.",
                Severity.INFO,
                code="DUPLICATE_SEGMENTS",
            )
        )
    if tiny + result.tiny_segment_count and (tiny or result.tiny_segment_count):
        if result.tiny_segment_count:
            result.notices.append(
                Notice(
                    f"{result.tiny_segment_count} tiny/degenerate segment(s) ignored.",
                    Severity.INFO,
                    code="TINY_SEGMENTS",
                )
            )
    if open_chains:
        result.notices.append(
            Notice(
                f"{open_chains} open contour(s) detected. Open contours cannot be "
                "nested. Check for gaps in the drawing.",
                Severity.WARNING,
                code="OPEN_CONTOUR",
            )
        )

    # 3) Classify containment over ALL rings together.
    classified = classify_containment(candidate_rings)

    # 4) Validate/repair each polygon, filter tiny ones.
    skipped_small = 0
    for poly in classified:
        fixed, notices = validate_and_repair(poly, tol)
        result.notices.extend(notices)
        if fixed is None:
            skipped_small += 1
            continue
        result.polygons.append(fixed)
    if skipped_small:
        result.notices.append(
            Notice(
                f"{skipped_small} fragment(s) below the minimum part area "
                f"({tol.min_part_area_mm2:g} mm²) were ignored.",
                Severity.INFO,
                code="TINY_FRAGMENTS",
            )
        )
    return result

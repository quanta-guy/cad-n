"""Programmatic DXF fixture builders (doc 14.1's fixture categories).

Each function returns an in-memory ezdxf Drawing so tests need no disk I/O.
``tools/make_fixtures.py`` persists them to a sample library for benchmarks and
the release bundle.
"""

from __future__ import annotations

import math

import ezdxf


def _new(units: int = 4):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = units  # 4 = mm
    return doc


def _rect(msp, x, y, w, h, layer="CUT", close=True):
    msp.add_lwpolyline(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
        close=close,
        dxfattribs={"layer": layer},
    )


# 1 -----------------------------------------------------------------------
def simple_rectangle(w=100.0, h=60.0):
    doc = _new()
    _rect(doc.modelspace(), 0, 0, w, h)
    return doc


# 2 -----------------------------------------------------------------------
def rectangle_with_hole():
    doc = _new()
    msp = doc.modelspace()
    _rect(msp, 0, 0, 100, 100)
    msp.add_circle((50, 50), radius=15, dxfattribs={"layer": "CUT"})  # hole
    return doc


# 3 -----------------------------------------------------------------------
def circle(r=25.0):
    doc = _new()
    doc.modelspace().add_circle((0, 0), radius=r, dxfattribs={"layer": "CUT"})
    return doc


# 4 -----------------------------------------------------------------------
def arc_profile(length=80.0, r=20.0):
    """An obround / slot made of two lines and two semicircle arcs."""
    doc = _new()
    msp = doc.modelspace()
    a = {"layer": "CUT"}
    msp.add_line((r, 0), (length - r, 0), dxfattribs=a)
    msp.add_arc((length - r, r), r, -90, 90, dxfattribs=a)
    msp.add_line((length - r, 2 * r), (r, 2 * r), dxfattribs=a)
    msp.add_arc((r, r), r, 90, 270, dxfattribs=a)
    return doc


# 5 -----------------------------------------------------------------------
def spline_profile():
    """A closed spline blob."""
    doc = _new()
    msp = doc.modelspace()
    pts = [(0, 0), (40, -10), (70, 20), (50, 60), (10, 50), (-15, 25)]
    s = msp.add_spline(fit_points=pts, dxfattribs={"layer": "CUT"})
    s.closed = True
    return doc


# 6 -----------------------------------------------------------------------
def multiple_parts():
    """Combined DXF: three distinct part shapes."""
    doc = _new()
    msp = doc.modelspace()
    _rect(msp, 0, 0, 50, 30)
    msp.add_circle((120, 20), radius=18, dxfattribs={"layer": "CUT"})
    msp.add_lwpolyline(
        [(200, 0), (260, 0), (260, 40), (230, 60), (200, 40)],
        close=True,
        dxfattribs={"layer": "CUT"},
    )
    return doc


# 7 -----------------------------------------------------------------------
def open_contour():
    """A rectangle missing one side (open) plus one good closed part."""
    doc = _new()
    msp = doc.modelspace()
    a = {"layer": "CUT"}
    # open: three sides only
    msp.add_line((0, 0), (40, 0), dxfattribs=a)
    msp.add_line((40, 0), (40, 30), dxfattribs=a)
    msp.add_line((40, 30), (0, 30), dxfattribs=a)
    # good closed part well away from the open one
    _rect(msp, 100, 0, 50, 50)
    return doc


# 8 -----------------------------------------------------------------------
def duplicate_geometry():
    """One rectangle drawn twice (overlapping duplicate edges)."""
    doc = _new()
    msp = doc.modelspace()
    for _ in range(2):
        msp.add_line((0, 0), (60, 0), dxfattribs={"layer": "CUT"})
        msp.add_line((60, 0), (60, 40), dxfattribs={"layer": "CUT"})
        msp.add_line((60, 40), (0, 40), dxfattribs={"layer": "CUT"})
        msp.add_line((0, 40), (0, 0), dxfattribs={"layer": "CUT"})
    return doc


# 9 -----------------------------------------------------------------------
def dimensions_and_text():
    """A real part on CUT, plus dimensions/text/leader on a DIM layer.

    The importer must NOT turn the dimension arrows or text into parts
    (doc section 18, the central correctness concern)."""
    doc = _new()
    msp = doc.modelspace()
    _rect(msp, 0, 0, 100, 60, layer="CUT")
    msp.add_text("PART A", dxfattribs={"layer": "DIM", "height": 5}).set_placement((10, 70))
    dim = msp.add_linear_dim(
        base=(0, -15), p1=(0, 0), p2=(100, 0),
        dxfattribs={"layer": "DIM"},
    )
    dim.render()
    return doc


# 10 ----------------------------------------------------------------------
def blocks_insert():
    """An L-shaped bracket with a hole, defined in a block and INSERTed."""
    doc = _new()
    blk = doc.blocks.new(name="BRKT")
    blk.add_lwpolyline(
        [(0, 0), (60, 0), (60, 20), (20, 20), (20, 50), (0, 50)],
        close=True,
        dxfattribs={"layer": "CUT"},
    )
    blk.add_circle((10, 10), radius=4, dxfattribs={"layer": "CUT"})  # hole
    doc.modelspace().add_blockref("BRKT", (5, 5), dxfattribs={"layer": "CUT"})
    return doc


# 11 ----------------------------------------------------------------------
def tiny_fragments():
    """A good part plus several sub-mm triangle fragments (arrowhead-like)."""
    doc = _new()
    msp = doc.modelspace()
    _rect(msp, 0, 0, 100, 100)
    for ox in (200, 210, 220):
        msp.add_lwpolyline(
            [(ox, 0), (ox + 0.3, 0), (ox + 0.15, 0.3)],
            close=True,
            dxfattribs={"layer": "CUT"},
        )
    return doc


# 12 ----------------------------------------------------------------------
def non_mm_units():
    """A 2 x 1 INCH rectangle (INSUNITS=1). Should become ~50.8 x 25.4 mm."""
    doc = _new(units=1)
    _rect(doc.modelspace(), 0, 0, 2.0, 1.0)
    return doc


# 13 ----------------------------------------------------------------------
def large_file(rows=20, cols=20, w=20.0, h=12.0, gap=8.0):
    """Grid of many small rectangles -> stress the importer/nester."""
    doc = _new()
    msp = doc.modelspace()
    for r in range(rows):
        for c in range(cols):
            _rect(msp, c * (w + gap), r * (h + gap), w, h)
    return doc


# 14 ----------------------------------------------------------------------
def part_too_large(w=5000.0, h=20.0):
    """A part wider than any normal sheet (for the nester's 'too large' path)."""
    doc = _new()
    _rect(doc.modelspace(), 0, 0, w, h)
    return doc


# 15 ----------------------------------------------------------------------
def common_cut_rectangles():
    """Two rectangles sharing a common edge, drawn as loose lines."""
    doc = _new()
    msp = doc.modelspace()
    a = {"layer": "CUT"}
    # left rect 0..50 x 0..30 ; right rect 50..100 x 0..30 ; shared edge x=50
    for (x0, x1) in ((0, 50), (50, 100)):
        msp.add_line((x0, 0), (x1, 0), dxfattribs=a)
        msp.add_line((x1, 0), (x1, 30), dxfattribs=a)
        msp.add_line((x1, 30), (x0, 30), dxfattribs=a)
        msp.add_line((x0, 30), (x0, 0), dxfattribs=a)
    return doc


ALL_BUILDERS = {
    "01_simple_rectangle": simple_rectangle,
    "02_rectangle_with_hole": rectangle_with_hole,
    "03_circle": circle,
    "04_arc_profile": arc_profile,
    "05_spline_profile": spline_profile,
    "06_multiple_parts": multiple_parts,
    "07_open_contour": open_contour,
    "08_duplicate_geometry": duplicate_geometry,
    "09_dimensions_and_text": dimensions_and_text,
    "10_blocks_insert": blocks_insert,
    "11_tiny_fragments": tiny_fragments,
    "12_non_mm_units": non_mm_units,
    "13_large_file": large_file,
    "14_part_too_large": part_too_large,
    "15_common_cut_rectangles": common_cut_rectangles,
}

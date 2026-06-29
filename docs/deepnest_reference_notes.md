# Deepnest / SVGNest Reference Notes

These notes are for algorithm comparison only. The SVGNest code under
Deepnest's `main` folder shows an MIT license, but CAD-N should still treat
Deepnest as reference material unless we do an explicit license and dependency
review. Use the public behavior and published algorithm ideas as references for
independent implementation.

Sources:

- Deepnest site: https://deepnest.io/
- Deepnest source/readme: https://github.com/Jack000/Deepnest
- SVGNest algorithm notes inside Deepnest: https://github.com/Jack000/Deepnest/tree/master/main
- SVGNest license file: https://github.com/Jack000/Deepnest/blob/master/main/LICENSE.txt

## What Deepnest Does Differently

Deepnest is based on SVGNest and advertises:

- common-line merging for laser/CNC cuts
- part-in-part placement
- bitmap/image nesting support
- DXF/SVG import/export
- speed-critical nesting code in C/C++
- path simplification/approximation for complex parts

The key algorithmic difference is that SVGNest/Deepnest uses No-Fit Polygons
(NFPs) and a genetic algorithm (GA), whereas CAD-N currently uses a greedy
bottom-left-fill placement with repeated seeded orderings.

## Core Mechanics To Learn From

### No-Fit Polygon Placement

For each already-placed polygon A and candidate polygon B, the NFP describes the
valid boundary positions where B can touch A without overlap. Candidate
placements are sampled from the NFP boundary rather than from only simple x/y
columns. This tends to find tighter true-shape layouts, especially around
concave profiles.

For the sheet/container, an Inner Fit Polygon (IFP) describes where a candidate
part can sit while staying inside the bin. Valid placements are effectively:

```text
inside sheet IFP - union(overlap-forbidden NFPs against placed parts)
```

### Genetic Search

Deepnest/SVGNest treats part order and rotations as a gene. Fitness is ranked by:

1. fewer unplaceable parts
2. fewer bins/sheets
3. tighter occupied width / material usage

The useful idea for CAD-N is not the exact GA code, but the structure:

- seed with large-first orders
- mutate part order and rotations
- cache expensive pairwise geometry work
- keep improving until the operator stops or a time limit is hit

### NFP Caching

NFPs are expensive but reusable. A cache key can include:

- stationary part id + rotation
- orbiting part id + rotation
- inside/outside mode
- spacing/kerf offset

This matters because GA attempts evaluate many similar orders. Without caching,
NFP-style placement can be slower than CAD-N's current Shapely collision checks.

### Integer Geometry Kernel

Deepnest uses C/C++ for speed-critical geometry and Boost polygon/Minkowski
convolution in its NFP path. CAD-N should not copy this implementation, but if we
add NFPs we should consider:

- robust integer scaling before polygon boolean operations
- a cacheable Minkowski/NFP module
- aggressive simplification of very dense DXF curves before optimization

## CAD-N Compared To Deepnest

CAD-N strengths today:

- safer DXF import cleanup and operator warnings
- explicit stock A/B handling
- validated DXF export
- deterministic greedy placement
- post-pack sheet shrinking to smaller stock
- easy-to-debug Python/Shapely geometry

Deepnest-style advantages CAD-N does not yet have:

- NFP-based candidate placement
- part-in-part nesting
- GA over both order and rotation
- long-running continuous improvement
- stronger use of concave voids
- faster repeated attempt evaluation through NFP caching

## Practical Roadmap For CAD-N

1. Keep the current BLF engine as the safe baseline.
2. Add a benchmark mode that records import time, nest time, sheet count, stock
   area, utilization, and failed parts for known DXFs.
3. Add a GA wrapper around the existing BLF engine first: mutate order/rotation,
   keep best layouts, and report convergence.
4. Add a small NFP prototype for polygons without holes, behind a feature flag.
5. Extend NFP to holes/part-in-part only after robust validation exists.
6. Cache pairwise geometry by part id, rotation, spacing and kerf.
7. Keep export validation as the final authority: no overlap and in-bounds checks
   must still gate every DXF export.

## Notes For The Current TO NEST.dxf Case

The recent CAD-N fixes are still consistent with Deepnest-style lessons:

- import verification exposed frame/contour issues before nesting
- endpoint tolerance repaired small drafting gaps
- multi-stock search now compares configurations
- post-pack sheet shrinking reduced an underused `2500x1500` sheet to `2000x1500`

The next big improvement for this file would be GA search over part order and
rotations, then NFP placement for tighter true-shape layouts.

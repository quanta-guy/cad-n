# CAD-N Methodology Snapshot - 2026-06-29

Purpose: stable rollback point before adding a genetic-algorithm optimizer.

## Import And Verification

- DXF entities are converted into Shapely geometry, then cleaned before nesting.
- Endpoint welding uses `snap_tolerance_mm = 0.3` by default to repair small
  drafting gaps that would otherwise create broken profiles.
- Large enclosing rectangular frames are ignored during import when they contain
  nested profiles. This prevents the sheet border/frame from being treated as a
  part.
- Identical imported profiles are grouped into one `Part` with quantity, while
  `metadata["preview_instances"]` preserves the original source positions for
  import preview.
- Import preview draws the original CAD layout before nesting, so errors can be
  spotted before optimization starts.

## UI And Operator Flow

- Available stock defaults to:
  - Sheet A: `2500 x 1500 mm`
  - Sheet B: `2000 x 1500 mm`
- Sheet B is enabled by default so the engine can compare mixed stock options.
- Border margin defaults to `0 mm` for the current shop-stock workflow.
- The preview canvas supports two zoom modes:
  - `Fit parts`: focuses on placed/imported geometry.
  - `Fit sheet`: shows the whole sheet.
- Changing imported parts, quantities, or stock settings clears stale nest
  results and redraws the import preview.

## Current Nesting Engine

The current optimizer is deterministic greedy BLF with bounded randomized
retries, not yet a genetic algorithm.

Placement method:

- Prepare each part into allowed orientation variants.
- Try several orderings:
  - configured strategy
  - longest side descending
  - height descending
  - area descending
  - seeded random shuffles up to `attempt_count`
- For each ordering, run bottom-left-fill placement against the candidate sheet
  list.
- Score attempts by:
  1. most placed instances
  2. least total purchased stock area
  3. tightest used sheet length

## Multi-Stock Search

When more than one sheet size is enabled, CAD-N evaluates bounded stock-count
configurations instead of committing to only one stock type.

- Candidate mixes are generated from the usable-area frontier.
- Configurations that cannot cover exclusive large-part area are skipped.
- Priority configurations near the area lower bound are tested first.
- Search is capped by `_MAX_CONFIGS = 24` and keeps `_MAX_KEEP = 12` ranked
  alternatives for the operator.
- The selected result is the feasible configuration with the lowest purchased
  stock area by the current greedy packer.

## Sheet Shrink Pass

After placement, CAD-N checks each used sheet independently. If all placed
geometry on a larger stock sheet fits a smaller enabled stock size, the sheet is
replaced by the smaller stock and placements are translated to the smaller
sheet's usable origin.

This is why an underused `2500 x 1500` sheet can become `2000 x 1500` after the
packer completes.

## Current Optimality Guarantees

CAD-N reports an area-based lower bound, but the current result is not a proof
of mathematical optimality.

The lower bound answers: "How many sheets are required by total area alone?"
It does not prove that the shapes can physically fit that many sheets because
geometry, rotations, holes, concavity, and collision constraints still matter.

Current validation guarantees are practical:

- no placed part may overlap another placed part
- all placed geometry must stay within sheet bounds
- export selfcheck reopens generated DXF geometry
- tests cover import cleanup, preview grouping, stock shrinking, and nesting
  result behavior

## Why GA Is The Next Sensible Step

The screenshot case shows the limitation clearly: local BLF placement chooses a
valid arrangement, but a different order/rotation sequence could likely fit the
same shapes on smaller stock.

A genetic algorithm should improve this without replacing the whole engine:

- chromosome = part ordering plus orientation choices
- fitness = failed part penalty, sheet count, purchased stock area, utilization,
  and compactness
- initial population = current deterministic orders plus random shuffles
- mutation = swap parts, reverse ranges, rotate selected parts
- crossover = order-preserving mix of two parent sequences
- evaluation = reuse the existing placement and validation path

This keeps the current BLF engine as the safe baseline while allowing broader
search over the math problem.

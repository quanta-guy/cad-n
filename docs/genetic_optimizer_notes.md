# Genetic Optimizer Notes

The area calculation is useful, but it is only a lower bound. A layout can have
enough total sheet area and still fail because the shapes collide, block each
other, or need a different ordering/orientation.

CAD-N now treats this as a search problem:

- chromosome = flat part-instance order plus preferred rotation variant
- evaluator = existing BLF placer, sheet bounds checks, and overlap checks
- fitness = most parts placed, then least stock area, then tighter used length
- seed population = current deterministic orderings plus random shuffles
- mutation = swap instances, reverse short ranges, rotate selected instances
- crossover = order-preserving splice between two parent layouts
- safety rule = GA never bypasses validation; it only proposes an order and
  orientation, then the normal placer proves whether it is valid

This is intentionally a hybrid optimizer. The committed baseline remains the
simple deterministic BLF search. With `enable_genetic_search` turned on, CAD-N
uses GA candidates only when they score better than the baseline attempt.

For the current `TO NEST.dxf` behavior, GA is the right next experiment because
the remaining issue is not "is there enough area?" It is "can another sequence
of placements use the available rectangles more intelligently?"

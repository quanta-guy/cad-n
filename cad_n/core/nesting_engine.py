"""Nesting engine orchestration (doc 10.1).

Runs several BLF packing attempts with different part orderings (largest-area,
longest-side, tallest, then seeded random shuffles), keeps the best by
(most parts placed, least stock area, tightest used length), and assembles a
:class:`NestingResult` with utilization and remnant metrics (doc 13).

With a single stock size it fills sheets of that size. Given several stock sizes
it additionally searches across stock-mix configurations (how many of each size)
and returns the mix that places every part using the least total stock area,
keeping the ranked alternatives on the result for the operator to choose from.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional

from .models import (
    ConfigOption,
    NestingResult,
    NestingSettings,
    Notice,
    Part,
    PlacementStrategy,
    Severity,
    Sheet,
    UnnestedPart,
)
from .placement import AttemptResult, PreparedPart, prepare_part, run_attempt

ProgressCb = Optional[Callable[[int, int, str], None]]

# Bound the stock-mix search: how many configurations to evaluate, and how many
# ranked ones to keep on the result for the operator to choose from.
_MAX_CONFIGS = 24
_MAX_KEEP = 12


# --------------------------------------------------------------------------- #
# Part ordering + scoring helpers
# --------------------------------------------------------------------------- #
def _order(prepared: list[PreparedPart], strategy: PlacementStrategy) -> list[PreparedPart]:
    if strategy is PlacementStrategy.AREA_DESC:
        key = lambda pp: -pp.area
    elif strategy is PlacementStrategy.LONGEST_SIDE:
        key = lambda pp: -max(pp.variants[0].w, pp.variants[0].h) if pp.variants else 0
    elif strategy is PlacementStrategy.HEIGHT_DESC:
        key = lambda pp: -(pp.variants[0].h if pp.variants else 0)
    else:
        return list(prepared)
    return sorted(prepared, key=key)


def _build_orderings(prepared: list[PreparedPart],
                     settings: NestingSettings) -> list[list[PreparedPart]]:
    """Deterministic strategy orderings first, then seeded random shuffles."""
    orderings: list[list[PreparedPart]] = []
    seen_first: set[tuple] = set()
    for strat in (settings.placement_strategy, PlacementStrategy.LONGEST_SIDE,
                  PlacementStrategy.HEIGHT_DESC, PlacementStrategy.AREA_DESC):
        order = _order(prepared, strat)
        sig = tuple(id(pp) for pp in order)
        if sig not in seen_first:
            seen_first.add(sig)
            orderings.append(order)
    rng = random.Random(settings.random_seed)
    attempt_count = max(1, settings.attempt_count)
    while len(orderings) < attempt_count:
        shuffled = list(prepared)
        rng.shuffle(shuffled)
        orderings.append(shuffled)
    return orderings[:attempt_count]


def _fits_any(pp: PreparedPart, sheets: list[Sheet]) -> bool:
    """True if the part fits the usable area of at least one stock type."""
    eps = 1e-6
    for sheet in sheets:
        uw, uh = sheet.usable_width, sheet.usable_height
        if any(v.w <= uw + eps and v.h <= uh + eps for v in pp.variants):
            return True
    return False


def _stock_area(attempt: AttemptResult) -> float:
    """Total purchased sheet area (full size) across the sheets actually used."""
    return sum(s.width_mm * s.height_mm for s in attempt.sheets)


def _score(attempt: AttemptResult) -> tuple:
    by_sheet: dict[int, float] = {}
    for pl in attempt.placements:
        mx = pl.polygon_world.bounds[2]
        by_sheet[pl.sheet_index] = max(by_sheet.get(pl.sheet_index, 0.0), mx)
    used_total = sum(by_sheet.values())
    # Lower is better: most placed, then least stock area, then tightest.
    return (-len(attempt.placements), _stock_area(attempt), used_total)


def _search(prepared: list[PreparedPart], bins: list[Sheet],
            settings: NestingSettings, t0: float,
            open_until_fit: bool = False) -> tuple[AttemptResult, bool]:
    """Best AttemptResult over several part orderings packed into ``bins``.

    Returns ``(best, hit_time_limit)``."""
    best: Optional[AttemptResult] = None
    best_key: Optional[tuple] = None
    hit_limit = False
    for order in _build_orderings(prepared, settings):
        attempt = run_attempt(order, [], bins, settings, open_until_fit=open_until_fit)
        key = _score(attempt)
        if best_key is None or key < best_key:
            best, best_key = attempt, key
        if time.perf_counter() - t0 >= settings.time_limit_sec:
            hit_limit = True
            break
    assert best is not None
    return best, hit_limit


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def nest(
    parts: list[Part],
    sheet,                      # Sheet or list[Sheet] (one or more stock sizes)
    settings: NestingSettings,
    progress: ProgressCb = None,
) -> NestingResult:
    t0 = time.perf_counter()
    sheet_types = [sheet] if isinstance(sheet, Sheet) else list(sheet)
    result = NestingResult(sheet=sheet_types[0] if sheet_types else None)

    real_parts = [p for p in parts if p.quantity > 0 and not p.geom.is_empty]
    if not real_parts:
        result.notices.append(Notice("No parts to nest.", Severity.WARNING, code="NO_PARTS"))
        result.runtime_sec = time.perf_counter() - t0
        return result

    valid_types = [s for s in sheet_types if s.usable_area > 0]
    if not valid_types:
        result.notices.append(Notice(
            "Sheet usable area is zero (margins too large for the sheet size).",
            Severity.ERROR, code="BAD_SHEET"))
        result.runtime_sec = time.perf_counter() - t0
        return result

    prepared = [prepare_part(p, settings) for p in real_parts]
    pp_by_id = {pp.part.id: pp for pp in prepared}
    total_instances = sum(pp.part.quantity for pp in prepared)

    if len(valid_types) == 1:
        if progress:
            progress(0, 1, "Nesting...")
        sheet0 = valid_types[0]
        max_sheets = max(1, min(int(sheet0.quantity_available), total_instances))
        bins = [sheet0] * max_sheets
        best, hit_limit = _search(prepared, bins, settings, t0)
        _assemble(result, best, valid_types, settings, pp_by_id, real_parts)
        if hit_limit:
            result.notices.append(Notice(
                f"Stopped after the {settings.time_limit_sec:g}s time limit.",
                Severity.INFO, code="TIME_LIMIT"))
    else:
        part_area = sum(pp.area * pp.part.quantity for pp in prepared)
        result = _multi(prepared, valid_types, settings, t0, progress,
                        pp_by_id, real_parts, part_area, total_instances)

    result.runtime_sec = time.perf_counter() - t0
    if progress:
        progress(1, 1, "Done")
    return result


# --------------------------------------------------------------------------- #
# Multi-stock configuration search
# --------------------------------------------------------------------------- #
def _enumerate_configs(types: list[Sheet], part_area: float,
                       instances: int) -> list[tuple]:
    """Candidate stock-mix count vectors to evaluate.

    Pruned to the area frontier (a mix can only place everything if its total
    usable area covers the parts) and capped, always including the all-maxed
    fallback so at least one feasible mix is tried.
    """
    kmax = [max(0, min(int(t.quantity_available), instances)) for t in types]
    usable = [t.usable_area for t in types]
    full = [t.width_mm * t.height_mm for t in types]
    eps = 1e-6
    configs: set[tuple] = set()

    if len(types) == 2:
        kA, kB = kmax
        aU, bU = usable
        for nA in range(kA + 1):
            rem = part_area - nA * aU
            if rem <= 0:
                nB_min = 0
            elif bU > 0:
                nB_min = math.ceil(rem / bU)
            else:
                nB_min = kB
            # nB_min covers the area; +1 gives slack for packing inefficiency.
            for nB in (nB_min, nB_min + 1):
                if 0 <= nB <= kB and (nA or nB) and nA * aU + nB * bU >= part_area - eps:
                    configs.add((nA, nB))
        for fb in ((kA, 0), (0, kB), (kA, kB)):
            if fb != (0, 0) and fb[0] * aU + fb[1] * bU >= part_area - eps:
                configs.add(fb)
    else:
        # General fallback (1 or 3+ types): each type maxed alone, plus all maxed.
        for i in range(len(types)):
            vec = [0] * len(types)
            vec[i] = kmax[i]
            if sum(vec[j] * usable[j] for j in range(len(types))) >= part_area - eps:
                configs.add(tuple(vec))
        configs.add(tuple(kmax))

    allmax = tuple(kmax)
    ordered = sorted(configs, key=lambda c: sum(c[j] * full[j] for j in range(len(types))))
    capped = ordered[:_MAX_CONFIGS]
    if allmax in configs and allmax not in capped:
        capped = capped[:_MAX_CONFIGS - 1] + [allmax]
    return capped or [allmax]


def _bins_for(counts: tuple, types: list[Sheet]) -> list[Sheet]:
    """Build the ordered bin list for a config, largest stock first so big
    sheets fill before small ones."""
    bins: list[Sheet] = []
    for n, t in zip(counts, types):
        bins.extend([t] * n)
    bins.sort(key=lambda s: -(s.width_mm * s.height_mm))
    return bins


def _realised_counts(sheets: list[Sheet]) -> list[tuple]:
    """(name, number used) per stock type, in first-seen order."""
    order: list[str] = []
    cnt: dict[str, int] = {}
    for s in sheets:
        if s.name not in cnt:
            order.append(s.name)
            cnt[s.name] = 0
        cnt[s.name] += 1
    return [(name, cnt[name]) for name in order]


def _config_label(counts: list[tuple], types: list[Sheet]) -> str:
    by_name = {t.name: t for t in types}
    chunks = []
    for name, n in counts:
        t = by_name.get(name)
        dim = f"{t.width_mm:g}x{t.height_mm:g}" if t else "?"
        chunks.append(f"{n}x {name} ({dim})")
    return " + ".join(chunks) if chunks else "(no sheets)"


def _make_option(attempt: AttemptResult, types, settings, pp_by_id,
                 real_parts) -> ConfigOption:
    r = NestingResult(sheet=types[0])
    _assemble(r, attempt, types, settings, pp_by_id, real_parts)
    stock_area = _stock_area(attempt)
    placed_area = sum(pl.area for pl in attempt.placements)
    counts = _realised_counts(attempt.sheets)
    return ConfigOption(
        label=_config_label(counts, types),
        counts=counts,
        stock_area=stock_area,
        waste_area=max(0.0, stock_area - placed_area),
        utilization=r.total_utilization,
        sheets_used=r.sheet_count_used,
        all_placed=(r.total_parts_failed == 0),
        parts_failed=r.total_parts_failed,
        result=r,
    )


def _rank_key(opt: ConfigOption) -> tuple:
    # All-placed first; then least stock area (the objective); then fewest
    # sheets; then least waste.
    return (0 if opt.all_placed else 1, opt.stock_area, opt.sheets_used, opt.waste_area)


def _multi(prepared, types, settings, t0, progress, pp_by_id, real_parts,
           part_area, total_instances) -> NestingResult:
    candidates = _enumerate_configs(types, part_area, total_instances)
    options: list[ConfigOption] = []
    hit_limit = False
    n = len(candidates)
    for i, counts in enumerate(candidates):
        if progress:
            progress(i, n, f"Stock configuration {i + 1}/{n}")
        bins = _bins_for(counts, types)
        if not bins:
            continue
        best, hl = _search(prepared, bins, settings, t0, open_until_fit=True)
        hit_limit = hit_limit or hl
        options.append(_make_option(best, types, settings, pp_by_id, real_parts))
        if time.perf_counter() - t0 >= settings.time_limit_sec:
            hit_limit = True
            break

    # Different candidates can realise the same usage (a bin may go unused);
    # dedupe by realised mix, keep the best, then rank best-first.
    best_by_counts: dict[tuple, ConfigOption] = {}
    for opt in options:
        key = tuple(opt.counts)
        cur = best_by_counts.get(key)
        if cur is None or _rank_key(opt) < _rank_key(cur):
            best_by_counts[key] = opt
    ranked = sorted(best_by_counts.values(), key=_rank_key)

    if not ranked:
        empty = NestingResult(sheet=types[0])
        _assemble(empty, AttemptResult(), types, settings, pp_by_id, real_parts)
        return empty

    chosen = ranked[0]
    result = chosen.result
    result.configurations = ranked[:_MAX_KEEP]
    result.notices.insert(
        1 if result.notices else 0,
        Notice(
            f"Best stock mix by least area: {chosen.label} "
            f"({chosen.sheets_used} sheet(s), {chosen.utilization * 100:.1f}% util). "
            f"{len(ranked)} configuration(s) available to choose from.",
            Severity.INFO, code="CONFIG_CHOSEN",
        ),
    )
    if hit_limit:
        result.notices.append(Notice(
            f"Stopped the stock-mix search at the {settings.time_limit_sec:g}s time limit.",
            Severity.INFO, code="TIME_LIMIT"))
    return result


# --------------------------------------------------------------------------- #
# Result assembly
# --------------------------------------------------------------------------- #
def _assemble(result, attempt, types, settings, pp_by_id, real_parts):
    result.placements = attempt.placements
    result.sheet_count_used = attempt.sheets_used
    result.sheets = list(attempt.sheets)
    result.sheet = result.sheets[0] if result.sheets else types[0]

    used = attempt.sheets_used
    placed_area = [0.0] * used
    used_len = [0.0] * used
    for pl in attempt.placements:
        placed_area[pl.sheet_index] += pl.area
        used_len[pl.sheet_index] = max(used_len[pl.sheet_index], pl.polygon_world.bounds[2])

    result.utilization_by_sheet = [
        (placed_area[i] / result.sheets[i].usable_area
         if result.sheets[i].usable_area else 0.0)
        for i in range(used)
    ]
    result.used_length_by_sheet = used_len
    result.remnant_length_by_sheet = [
        max(0.0, result.sheets[i].width_mm - used_len[i] - result.sheets[i].margin_mm)
        for i in range(used)
    ]
    total_placed = sum(placed_area)
    denom = sum(s.usable_area for s in result.sheets)
    result.total_utilization = total_placed / denom if denom else 0.0

    # Unnested parts with plain-English reasons.
    for part_id, qty in attempt.failed.items():
        if qty <= 0:
            continue
        pp = pp_by_id[part_id]
        too_large = not _fits_any(pp, types)
        reason = (
            "Part is larger than the usable area of every available sheet in "
            "every allowed rotation."
            if too_large
            else "No room left on the available sheets."
        )
        result.unnested_parts.append(
            UnnestedPart(part_id=part_id, part_name=pp.part.name,
                         quantity_failed=qty, reason=reason))
        sev = Severity.ERROR if too_large else Severity.WARNING
        result.notices.append(Notice(
            f"Part '{pp.part.name}': {qty} instance(s) not nested. {reason}",
            sev, code="UNNESTED", part_name=pp.part.name))

    nested = len(attempt.placements)
    requested = sum(p.quantity for p in real_parts)
    result.notices.insert(0, Notice(
        f"Nested {nested}/{requested} part instance(s) on {attempt.sheets_used} "
        f"sheet(s); total utilization {result.total_utilization * 100:.1f}%.",
        Severity.INFO, code="NEST_SUMMARY"))

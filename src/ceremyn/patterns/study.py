"""Historical performance of detected patterns: what happened after each one fired.

This is what keeps pattern output backtested rather than an unexplained assertion
(see ARCHITECTURE_DECISIONS.md / ROADMAP_V2.md): every (pattern name, direction) pair
is reported with its own historical hit rate and average forward return, computed
directly from the same candle history the patterns were detected on.
"""

from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.domain import Candle, Pattern
from ceremyn.domain.enums import PatternDirection

_MIN_OCCURRENCES_FOR_SIGNIFICANCE = 10


class PatternPerformance(BaseModel):
    """Aggregated historical outcome for one (pattern name, direction) pair, across
    every time it fired in the studied history."""

    model_config = ConfigDict(frozen=True)

    pattern_name: str = Field(min_length=1)
    direction: PatternDirection
    occurrences: int = Field(ge=0)
    # None when there weren't enough candles after any occurrence to measure a
    # forward return yet -- not the same as "measured and found no edge" (0.0).
    hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    average_forward_return_pct: float | None = None

    @property
    def is_significant(self) -> bool:
        """A conservative usefulness bar: enough occurrences to trust the rate at all.

        Deliberately not "profitable" or "reliable" -- just "measured enough times
        to not be noise." Callers still judge the actual hit rate/return themselves.
        """
        return self.occurrences >= _MIN_OCCURRENCES_FOR_SIGNIFICANCE


PerformanceHalves = tuple[PatternPerformance | None, PatternPerformance | None]


def _forward_return_pct(candles: tuple[Candle, ...], index: int, forward_days: int) -> float | None:
    if index + forward_days >= len(candles):
        return None
    entry = candles[index].close
    exit_price = candles[index + forward_days].close
    if entry <= 0:
        return None
    return float((exit_price - entry) / entry * Decimal(100))


def historical_performance(
    candles: tuple[Candle, ...],
    patterns: tuple[Pattern, ...],
    *,
    forward_days: int = 5,
) -> tuple[PatternPerformance, ...]:
    """Group `patterns` by (name, direction) and compute each pair's historical hit rate.

    A "hit" is a forward move in the direction the pattern implied over
    `forward_days` candles (bullish -> positive return, bearish -> negative return).
    Occurrences with fewer than `forward_days` candles remaining after them are
    excluded from that pair's stats -- no future to measure against yet.
    """
    by_key: dict[tuple[str, PatternDirection], list[Pattern]] = defaultdict(list)
    for pattern in patterns:
        by_key[(pattern.name, pattern.direction)].append(pattern)

    index_by_timestamp = {candle.timestamp: i for i, candle in enumerate(candles)}

    results: list[PatternPerformance] = []
    for (name, direction), occurrences in sorted(by_key.items()):
        returns: list[float] = []
        hits = 0
        for occurrence in occurrences:
            index = index_by_timestamp.get(occurrence.detected_at)
            if index is None:
                continue
            forward_return = _forward_return_pct(candles, index, forward_days)
            if forward_return is None:
                continue
            returns.append(forward_return)
            implied_positive = direction is PatternDirection.BULLISH
            if (forward_return > 0) == implied_positive:
                hits += 1
        results.append(
            PatternPerformance(
                pattern_name=name,
                direction=direction,
                occurrences=len(occurrences),
                hit_rate=(hits / len(returns)) if returns else None,
                average_forward_return_pct=(sum(returns) / len(returns)) if returns else None,
            )
        )
    return tuple(results)


def historical_performance_by_half(
    candles: tuple[Candle, ...],
    patterns: tuple[Pattern, ...],
    *,
    forward_days: int = 5,
) -> dict[tuple[str, PatternDirection], PerformanceHalves]:
    """Split `patterns` at the chronological midpoint of `candles` into an
    earlier half and a later half -- never shuffled, this is time-series data
    -- and compute each (name, direction) pair's `historical_performance`
    independently within each half.

    A single-pass, whole-window hit rate can't tell a genuine edge from a
    pattern that only happened to work in one slice of history: with
    thousands of (symbol, pattern, direction) combinations tested across a
    real scan, some will clear a hit-rate bar by chance alone. Requiring the
    SAME bar to hold twice, independently, in non-overlapping history is a
    real (if crude) out-of-sample check that a single whole-window average
    cannot provide. `None` for a half means the pattern never fired (with a
    measurable forward return) in that half at all -- itself a reason not to
    trust it, not a reason to fall back to the other half's number.
    """
    if not candles:
        return {}
    midpoint = candles[len(candles) // 2].timestamp
    earlier = tuple(p for p in patterns if p.detected_at < midpoint)
    later = tuple(p for p in patterns if p.detected_at >= midpoint)
    earlier_by_key = {
        (p.pattern_name, p.direction): p
        for p in historical_performance(candles, earlier, forward_days=forward_days)
    }
    later_by_key = {
        (p.pattern_name, p.direction): p
        for p in historical_performance(candles, later, forward_days=forward_days)
    }
    keys = {(p.name, p.direction) for p in patterns}
    return {key: (earlier_by_key.get(key), later_by_key.get(key)) for key in keys}

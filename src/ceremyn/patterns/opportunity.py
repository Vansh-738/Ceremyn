"""Rank live pattern occurrences across a watchlist into `Opportunity` objects.

Turns the per-symbol pattern scan into an actual cross-asset "what should I look at
right now" list: for each symbol, only pattern(s) detected on the LATEST candle are
live opportunities (not every historical occurrence, just what just fired), each
scored by its own backtested hit rate and average forward return, then ranked.
"""

from datetime import timedelta

from ceremyn.domain import Candle, Opportunity, Pattern, PatternTrackRecord
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns.candlestick import detect as detect_candlestick
from ceremyn.patterns.chart_shape import detect as detect_chart_shapes
from ceremyn.patterns.double_pattern import detect as detect_double_patterns
from ceremyn.patterns.head_shoulders import detect as detect_head_shoulders
from ceremyn.patterns.study import historical_performance
from ceremyn.patterns.swing import detect as detect_swing

DEFAULT_MIN_OCCURRENCES = 10
DEFAULT_MIN_CANDLES = 20
# A pattern that historically favored its own claimed direction less than half the
# time is, by definition, not evidence FOR that direction -- a large average move
# cannot make up for a coin-flip-or-worse hit rate. Strictly greater than 0.5, not
# >=: exactly 50% is no better than chance either.
DEFAULT_MIN_HIT_RATE = 0.5
# 0.0 = off by default: the reverse of DEFAULT_MIN_HIT_RATE's "no evidence" bar --
# this is a "not worth acting on even with good evidence" bar, opt-in per caller.
DEFAULT_MIN_AVG_FORWARD_RETURN_PCT = 0.0
# A symbol's own "latest bar" can be stale relative to the rest of the market --
# a thinly-traded or suspended stock that last appeared in bhavcopy weeks or
# months ago must not be surfaced as a "live" opportunity just because that old
# bar happens to be the last one in ITS history. Measured against the newest bar
# across the whole scan, not today's wall-clock date, so this works identically
# in a live scan and a historical backtest.
DEFAULT_MAX_STALENESS_DAYS = 5


def find_opportunities(
    candles_by_symbol: dict[str, tuple[Candle, ...]],
    asset_class_by_symbol: dict[str, AssetClass],
    *,
    forward_days: int = 5,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
    min_hit_rate: float = DEFAULT_MIN_HIT_RATE,
    min_avg_forward_return_pct: float = DEFAULT_MIN_AVG_FORWARD_RETURN_PCT,
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> tuple[Opportunity, ...]:
    """Scan every symbol's candle history, detect patterns, and rank the ones that
    fired on the latest bar by their own historical track record.

    A pattern with fewer than `min_occurrences` historical firings for a symbol, or
    a historical hit rate at or below `min_hit_rate`, is never surfaced as an
    Opportunity there. Not enough evidence, or evidence the pattern doesn't actually
    favor its own claimed direction, is excluded outright -- never ranked highly
    just because the average move happens to be large. `min_avg_forward_return_pct`
    is the opposite kind of bar: good evidence for a move too small to bother
    with. Compared against the *magnitude* of the average move (`abs(...)`), not
    its sign -- a strong bearish setup is exactly as real an opportunity as a
    strong bullish one, just in the other direction. A symbol whose own latest bar
    trails the scan's newest bar by more than `max_staleness_days` is skipped
    entirely -- its "opportunity" would really just be stale history.
    """
    bar_timestamps = [candles[-1].timestamp for candles in candles_by_symbol.values() if candles]
    if not bar_timestamps:
        return ()
    newest_bar = max(bar_timestamps)
    staleness_cutoff = newest_bar - timedelta(days=max_staleness_days)

    opportunities: list[Opportunity] = []
    for symbol, candles in candles_by_symbol.items():
        if len(candles) < DEFAULT_MIN_CANDLES:
            continue
        latest_timestamp = candles[-1].timestamp
        if latest_timestamp < staleness_cutoff:
            continue
        patterns: tuple[Pattern, ...] = (
            detect_candlestick(candles, tradingsymbol=symbol)
            + detect_swing(candles, tradingsymbol=symbol)
            + detect_chart_shapes(candles, tradingsymbol=symbol)
            + detect_double_patterns(candles, tradingsymbol=symbol)
            + detect_head_shoulders(candles, tradingsymbol=symbol)
        )
        performance = {
            (p.pattern_name, p.direction): p
            for p in historical_performance(candles, patterns, forward_days=forward_days)
        }
        asset_class = asset_class_by_symbol.get(symbol, AssetClass.EQUITY)
        for pattern in patterns:
            if pattern.detected_at != latest_timestamp:
                continue
            perf = performance.get((pattern.name, pattern.direction))
            if (
                perf is None
                or perf.hit_rate is None
                or perf.occurrences < min_occurrences
                or perf.hit_rate <= min_hit_rate
                or abs(perf.average_forward_return_pct or 0.0) < min_avg_forward_return_pct
            ):
                continue
            opportunities.append(
                Opportunity(
                    tradingsymbol=symbol,
                    asset_class=asset_class,
                    pattern_name=pattern.name,
                    direction=pattern.direction,
                    detected_at=pattern.detected_at,
                    source=pattern.source,
                    occurrences=perf.occurrences,
                    hit_rate=perf.hit_rate,
                    average_forward_return_pct=perf.average_forward_return_pct or 0.0,
                    forward_days=forward_days,
                )
            )
    return tuple(sorted(opportunities, key=lambda o: o.edge_score, reverse=True))


def analyze_symbol(
    candles: tuple[Candle, ...],
    *,
    forward_days: int = 5,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
    min_hit_rate: float = DEFAULT_MIN_HIT_RATE,
    min_avg_forward_return_pct: float = DEFAULT_MIN_AVG_FORWARD_RETURN_PCT,
) -> tuple[PatternTrackRecord, ...]:
    """Every pattern ever detected across one symbol's full history, each with its
    own historical track record -- a deliberate, one-symbol "tell me everything
    you know" lookup, not the narrower cross-market "what fired today and clears
    the quality bar" view `find_opportunities` gives.

    Unlike `find_opportunities`, nothing here is excluded for failing the quality
    bar (`min_occurrences`/`min_hit_rate`/`min_avg_forward_return_pct`) -- a
    single symbol's weaker patterns are still real information about it. Each
    record instead carries `is_opportunity_grade`, so a caller can see exactly
    which ones would have made the cross-market cut and which wouldn't.
    """
    if len(candles) < DEFAULT_MIN_CANDLES:
        return ()
    latest_timestamp = candles[-1].timestamp
    patterns: tuple[Pattern, ...] = (
        detect_candlestick(candles)
        + detect_swing(candles)
        + detect_chart_shapes(candles)
        + detect_double_patterns(candles)
        + detect_head_shoulders(candles)
    )
    if not patterns:
        return ()
    source_by_key = {(p.name, p.direction): p.source for p in patterns}
    active_keys = {(p.name, p.direction) for p in patterns if p.detected_at == latest_timestamp}
    performance = historical_performance(candles, patterns, forward_days=forward_days)

    records = [
        PatternTrackRecord(
            pattern_name=perf.pattern_name,
            direction=perf.direction,
            source=source_by_key[(perf.pattern_name, perf.direction)],
            active_now=(perf.pattern_name, perf.direction) in active_keys,
            occurrences=perf.occurrences,
            hit_rate=perf.hit_rate,
            average_forward_return_pct=perf.average_forward_return_pct,
            forward_days=forward_days,
            is_opportunity_grade=(
                perf.hit_rate is not None
                and perf.occurrences >= min_occurrences
                and perf.hit_rate > min_hit_rate
                and abs(perf.average_forward_return_pct or 0.0) >= min_avg_forward_return_pct
            ),
        )
        for perf in performance
    ]
    return tuple(
        sorted(records, key=lambda r: (r.active_now, r.is_opportunity_grade), reverse=True)
    )

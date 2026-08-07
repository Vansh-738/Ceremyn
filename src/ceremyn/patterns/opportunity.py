"""Rank live pattern occurrences across a watchlist into `Opportunity` objects.

Turns the per-symbol pattern scan into an actual cross-asset "what should I look at
right now" list: for each symbol, only pattern(s) detected on the LATEST candle are
live opportunities (not every historical occurrence, just what just fired), each
scored by its own backtested hit rate and average forward return, then ranked.
"""

from datetime import timedelta

from ceremyn.domain import Candle, Opportunity, Pattern
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns.candlestick import detect
from ceremyn.patterns.study import historical_performance

DEFAULT_MIN_OCCURRENCES = 10
DEFAULT_MIN_CANDLES = 20
# A pattern that historically favored its own claimed direction less than half the
# time is, by definition, not evidence FOR that direction -- a large average move
# cannot make up for a coin-flip-or-worse hit rate. Strictly greater than 0.5, not
# >=: exactly 50% is no better than chance either.
DEFAULT_MIN_HIT_RATE = 0.5
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
    max_staleness_days: int = DEFAULT_MAX_STALENESS_DAYS,
) -> tuple[Opportunity, ...]:
    """Scan every symbol's candle history, detect patterns, and rank the ones that
    fired on the latest bar by their own historical track record.

    A pattern with fewer than `min_occurrences` historical firings for a symbol, or
    a historical hit rate at or below `min_hit_rate`, is never surfaced as an
    Opportunity there. Not enough evidence, or evidence the pattern doesn't actually
    favor its own claimed direction, is excluded outright -- never ranked highly
    just because the average move happens to be large. A symbol whose own latest
    bar trails the scan's newest bar by more than `max_staleness_days` is skipped
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
        patterns: tuple[Pattern, ...] = detect(candles, tradingsymbol=symbol)
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

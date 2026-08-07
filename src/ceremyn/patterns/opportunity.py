"""Rank live pattern occurrences across a watchlist into `Opportunity` objects.

Turns the per-symbol pattern scan into an actual cross-asset "what should I look at
right now" list: for each symbol, only pattern(s) detected on the LATEST candle are
live opportunities (not every historical occurrence, just what just fired), each
scored by its own backtested hit rate and average forward return, then ranked.
"""

from ceremyn.domain import Candle, Opportunity, Pattern
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns.candlestick import detect
from ceremyn.patterns.study import historical_performance

DEFAULT_MIN_OCCURRENCES = 10
DEFAULT_MIN_CANDLES = 20


def find_opportunities(
    candles_by_symbol: dict[str, tuple[Candle, ...]],
    asset_class_by_symbol: dict[str, AssetClass],
    *,
    forward_days: int = 5,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
) -> tuple[Opportunity, ...]:
    """Scan every symbol's candle history, detect patterns, and rank the ones that
    fired on the latest bar by their own historical track record.

    A pattern with fewer than `min_occurrences` historical firings for a symbol is
    never surfaced as an Opportunity there -- not enough evidence to trust a rate is
    excluded outright, never guessed at with a low-confidence number.
    """
    opportunities: list[Opportunity] = []
    for symbol, candles in candles_by_symbol.items():
        if len(candles) < DEFAULT_MIN_CANDLES:
            continue
        patterns: tuple[Pattern, ...] = detect(candles, tradingsymbol=symbol)
        performance = {
            (p.pattern_name, p.direction): p
            for p in historical_performance(candles, patterns, forward_days=forward_days)
        }
        latest_timestamp = candles[-1].timestamp
        asset_class = asset_class_by_symbol.get(symbol, AssetClass.EQUITY)
        for pattern in patterns:
            if pattern.detected_at != latest_timestamp:
                continue
            perf = performance.get((pattern.name, pattern.direction))
            if perf is None or perf.hit_rate is None or perf.occurrences < min_occurrences:
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

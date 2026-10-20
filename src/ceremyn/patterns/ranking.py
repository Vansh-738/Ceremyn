"""Non-overlapping evidence and scan-wide false-discovery control.

This is a research filter, not a probability of future profit. BY adjustment is
conservative under dependence between pattern tests on the same market history.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from scipy.stats import binomtest, false_discovery_control

from ceremyn.domain import Candle, Opportunity, Pattern
from ceremyn.domain.enums import AssetClass, PatternDirection
from ceremyn.domain.fundamentals import FundamentalScore
from ceremyn.patterns.candlestick import detect as detect_candlestick
from ceremyn.patterns.chart_shape import detect as detect_chart_shapes
from ceremyn.patterns.double_pattern import detect as detect_double_patterns
from ceremyn.patterns.head_shoulders import detect as detect_head_shoulders
from ceremyn.patterns.swing import detect as detect_swing


@dataclass(frozen=True)
class Evidence:
    occurrences: int
    hit_rate: float
    baseline_hit_rate: float
    excess_return: float
    average_return: float
    p_value: float


def deoverlap(indices: list[int], horizon: int) -> list[int]:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    kept: list[int] = []
    for index in sorted(set(indices)):
        if not kept or index - kept[-1] >= horizon:
            kept.append(index)
    return kept


def evidence(
    candles: tuple[Candle, ...],
    patterns: tuple[Pattern, ...],
    direction: PatternDirection,
    horizon: int,
    start: int = 0,
    end: int | None = None,
) -> Evidence:
    if horizon < 1:
        raise ValueError("horizon must be positive")
    end = len(candles) if end is None else end
    index = {c.timestamp: i for i, c in enumerate(candles)}
    returns = {
        i: float((candles[i + horizon].close / candles[i].close - 1) * 100)
        for i in range(start, max(start, end - horizon))
        if candles[i].close > 0
    }
    indices = deoverlap(
        [
            index[p.detected_at]
            for p in patterns
            if p.detected_at in index and index[p.detected_at] in returns
        ],
        horizon,
    )
    baseline = list(returns.values())
    values = [returns[i] for i in indices]
    if not values or not baseline:
        return Evidence(0, 0, 0, 0, 0, 1)
    sign = 1 if direction is PatternDirection.BULLISH else -1
    base_rate = sum(sign * value > 0 for value in baseline) / len(baseline)
    hits = sum(sign * value > 0 for value in values)
    average = sum(values) / len(values)
    return Evidence(
        len(values),
        hits / len(values),
        base_rate,
        sign * (average - sum(baseline) / len(baseline)),
        average,
        float(binomtest(hits, len(values), base_rate, alternative="greater").pvalue),
    )


def detect_patterns(candles: tuple[Candle, ...], symbol: str) -> tuple[Pattern, ...]:
    return tuple(
        p
        for detector in (
            detect_candlestick,
            detect_swing,
            detect_chart_shapes,
            detect_double_patterns,
            detect_head_shoulders,
        )
        for p in detector(candles, tradingsymbol=symbol)
    )


def find_ranked_opportunities(
    candles_by_symbol: dict[str, tuple[Candle, ...]],
    asset_class_by_symbol: dict[str, AssetClass],
    *,
    forward_days: int = 30,
    min_occurrences: int = 10,
    min_hit_rate: float = 0.5,
    min_avg_forward_return_pct: float = 0,
    max_staleness_days: int = 5,
    fdr_alpha: float = 0.1,
    fundamentals: dict[str, FundamentalScore] | None = None,
    require_fundamentals: bool = False,
) -> tuple[Opportunity, ...]:
    if not 0 < fdr_alpha < 1 or forward_days < 1:
        raise ValueError("invalid ranking thresholds")
    latest = max((cs[-1].timestamp for cs in candles_by_symbol.values() if cs), default=None)
    if latest is None:
        return ()
    trials: list[tuple[str, Pattern, Evidence, bool]] = []
    for symbol, candles in candles_by_symbol.items():
        if not candles or candles[-1].timestamp < latest - timedelta(days=max_staleness_days):
            continue
        groups: dict[tuple[str, PatternDirection], list[Pattern]] = defaultdict(list)
        for pattern in detect_patterns(candles, symbol):
            groups[(pattern.name, pattern.direction)].append(pattern)
        for (_, direction), occurrences in groups.items():
            if direction not in (PatternDirection.BULLISH, PatternDirection.BEARISH):
                continue
            patterns = tuple(occurrences)
            whole = evidence(candles, patterns, direction, forward_days)
            halves = [
                evidence(candles, patterns, direction, forward_days, start, end)
                for start, end in [(0, len(candles) // 2), (len(candles) // 2, len(candles))]
            ]
            sign = 1 if direction is PatternDirection.BULLISH else -1
            quality = all(
                e.occurrences >= min_occurrences
                and e.hit_rate > min_hit_rate
                and e.hit_rate > e.baseline_hit_rate
                and e.excess_return > 0
                and sign * e.average_return >= min_avg_forward_return_pct
                for e in [whole, *halves]
            )
            active = [p for p in patterns if p.detected_at == candles[-1].timestamp]
            # Include inactive and unsuccessful tests in multiplicity correction too.
            trials.append(
                (symbol, active[0] if active else patterns[-1], whole, bool(active) and quality)
            )
    if not trials:
        return ()
    adjusted = false_discovery_control(np.array([t[2].p_value for t in trials]), method="by")
    result = []
    for (symbol, pattern, stats, eligible), q_value in zip(trials, adjusted, strict=True):
        if not eligible or q_value > fdr_alpha:
            continue
        fundamental = (fundamentals or {}).get(symbol)
        if require_fundamentals and (
            fundamental is None
            or fundamental.as_of > pattern.detected_at
            or fundamental.red_flags
            or fundamental.checks_run < 6
            or len(fundamental.checks_passed) < 4
        ):
            continue
        result.append(
            Opportunity(
                tradingsymbol=symbol,
                asset_class=asset_class_by_symbol.get(symbol, AssetClass.EQUITY),
                pattern_name=pattern.name,
                direction=pattern.direction,
                detected_at=pattern.detected_at,
                source=pattern.source,
                occurrences=stats.occurrences,
                hit_rate=stats.hit_rate,
                average_forward_return_pct=stats.average_return,
                forward_days=forward_days,
                baseline_hit_rate=stats.baseline_hit_rate,
                hit_rate_lift=stats.hit_rate - stats.baseline_hit_rate,
                excess_return_pct=stats.excess_return,
                adjusted_p_value=float(q_value),
                research_use="long_candidate"
                if pattern.direction is PatternDirection.BULLISH
                else "avoid_or_exit",
            )
        )
    return tuple(
        sorted(result, key=lambda row: (-row.edge_score, row.tradingsymbol, row.pattern_name))
    )

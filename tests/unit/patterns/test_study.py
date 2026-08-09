from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ceremyn.domain import Candle, Pattern, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.study import (
    PatternPerformance,
    historical_performance,
    historical_performance_by_half,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
# Closes rise by exactly 1 per day: 100, 101, 102, ..., 109 -- forward returns are
# easy to hand-verify without relying on the code under test to compute them.
CLOSES = [Decimal(100 + i) for i in range(10)]
# A longer series for the by-half split tests -- 20 days, midpoint at index 10.
LONG_CLOSES = [Decimal(100 + i) for i in range(20)]


def _build_candles(closes: list[Decimal]) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            tradingsymbol="RELIANCE",
            timeframe=TimeFrame.DAY,
            timestamp=START + timedelta(days=i),
            open=close,
            high=close + Decimal(1),
            low=close - Decimal(1),
            close=close,
        )
        for i, close in enumerate(closes)
    )


def _candles() -> tuple[Candle, ...]:
    return _build_candles(CLOSES)


def _long_candles() -> tuple[Candle, ...]:
    return _build_candles(LONG_CLOSES)


def _pattern(
    name: str, direction: PatternDirection, index: int, candles: tuple[Candle, ...]
) -> Pattern:
    return Pattern(
        name=name,
        tradingsymbol="RELIANCE",
        detected_at=candles[index].timestamp,
        direction=direction,
        source="candlestick",
    )


def _expected_return(index: int, forward_days: int, closes: list[Decimal]) -> float:
    entry = closes[index]
    exit_ = closes[index + forward_days]
    return float((exit_ - entry) / entry * Decimal(100))


class TestHistoricalPerformance:
    def test_empty_patterns_returns_empty(self) -> None:
        assert historical_performance(_candles(), ()) == ()

    def test_bullish_hit_when_forward_return_positive(self) -> None:
        candles = _candles()
        patterns = (
            _pattern("TESTUP", PatternDirection.BULLISH, 0, candles),
            _pattern("TESTUP", PatternDirection.BULLISH, 5, candles),
        )
        (result,) = historical_performance(candles, patterns, forward_days=3)
        assert result.pattern_name == "TESTUP"
        assert result.direction is PatternDirection.BULLISH
        assert result.occurrences == 2
        assert result.hit_rate == pytest.approx(1.0)  # both forward moves were positive
        expected_avg = (_expected_return(0, 3, CLOSES) + _expected_return(5, 3, CLOSES)) / 2
        assert result.average_forward_return_pct == pytest.approx(expected_avg)

    def test_bearish_miss_when_forward_return_positive(self) -> None:
        """Prices rise every day in this fixture -- a BEARISH pattern implies a fall,
        so every occurrence here is a miss, not a hit."""
        candles = _candles()
        patterns = (_pattern("TESTDOWN", PatternDirection.BEARISH, 1, candles),)
        (result,) = historical_performance(candles, patterns, forward_days=3)
        assert result.occurrences == 1
        assert result.hit_rate == pytest.approx(0.0)
        assert result.average_forward_return_pct == pytest.approx(_expected_return(1, 3, CLOSES))

    def test_same_name_different_direction_grouped_separately(self) -> None:
        candles = _candles()
        patterns = (
            _pattern("TESTUP", PatternDirection.BULLISH, 0, candles),
            _pattern("TESTUP", PatternDirection.BEARISH, 2, candles),
        )
        results = historical_performance(candles, patterns, forward_days=3)
        assert len(results) == 2
        by_direction = {r.direction: r for r in results}
        assert by_direction[PatternDirection.BULLISH].hit_rate == pytest.approx(1.0)
        assert by_direction[PatternDirection.BEARISH].hit_rate == pytest.approx(0.0)

    def test_occurrence_too_close_to_end_excluded_from_stats(self) -> None:
        candles = _candles()
        patterns = (_pattern("TESTEDGE", PatternDirection.BULLISH, 9, candles),)  # last bar
        (result,) = historical_performance(candles, patterns, forward_days=3)
        assert result.occurrences == 1  # still counted as an occurrence...
        assert result.hit_rate is None  # ...but no forward return could be measured
        assert result.average_forward_return_pct is None

    def test_results_sorted_by_name_then_direction(self) -> None:
        candles = _candles()
        patterns = (
            _pattern("ZEBRA", PatternDirection.BULLISH, 0, candles),
            _pattern("ALPHA", PatternDirection.BEARISH, 1, candles),
        )
        results = historical_performance(candles, patterns, forward_days=1)
        assert [r.pattern_name for r in results] == ["ALPHA", "ZEBRA"]


class TestPatternPerformance:
    def test_is_significant_threshold(self) -> None:
        below = PatternPerformance(
            pattern_name="X", direction=PatternDirection.BULLISH, occurrences=9
        )
        at_threshold = PatternPerformance(
            pattern_name="X", direction=PatternDirection.BULLISH, occurrences=10
        )
        assert below.is_significant is False
        assert at_threshold.is_significant is True


class TestHistoricalPerformanceByHalf:
    def test_empty_candles_returns_empty_dict(self) -> None:
        assert historical_performance_by_half((), ()) == {}

    def test_splits_occurrences_by_the_chronological_midpoint(self) -> None:
        # 20 bars -> midpoint at index 10. One occurrence well before it (index 2),
        # one well after (index 15) -- never shuffled, split purely by time.
        candles = _long_candles()
        patterns = (
            _pattern("TESTUP", PatternDirection.BULLISH, 2, candles),
            _pattern("TESTUP", PatternDirection.BULLISH, 15, candles),
        )
        halves = historical_performance_by_half(candles, patterns, forward_days=1)
        early, late = halves[("TESTUP", PatternDirection.BULLISH)]
        expected_early = _expected_return(2, 1, LONG_CLOSES)
        expected_late = _expected_return(15, 1, LONG_CLOSES)
        assert early is not None and early.occurrences == 1
        assert early.average_forward_return_pct == pytest.approx(expected_early)
        assert late is not None and late.occurrences == 1
        assert late.average_forward_return_pct == pytest.approx(expected_late)

    def test_none_for_the_half_with_no_occurrences(self) -> None:
        """A pattern that only ever fired in the earlier half of history must not
        silently borrow the other half's number -- it's simply unconfirmed there."""
        candles = _long_candles()
        patterns = (_pattern("ONLYEARLY", PatternDirection.BULLISH, 2, candles),)
        halves = historical_performance_by_half(candles, patterns, forward_days=1)
        early, late = halves[("ONLYEARLY", PatternDirection.BULLISH)]
        assert early is not None and early.occurrences == 1
        assert late is None

    def test_boundary_bar_belongs_to_the_later_half(self) -> None:
        """The midpoint bar itself (index 10 of 20) is >= the split point, so it
        counts as the start of the later half, not the end of the earlier one."""
        candles = _long_candles()
        patterns = (_pattern("ONBOUNDARY", PatternDirection.BULLISH, 10, candles),)
        halves = historical_performance_by_half(candles, patterns, forward_days=1)
        early, late = halves[("ONBOUNDARY", PatternDirection.BULLISH)]
        assert early is None
        assert late is not None and late.occurrences == 1

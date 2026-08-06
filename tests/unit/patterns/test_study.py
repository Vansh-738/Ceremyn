from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ceremyn.domain import Candle, Pattern, TimeFrame
from ceremyn.domain.enums import PatternDirection
from ceremyn.patterns.study import PatternPerformance, historical_performance

START = datetime(2026, 1, 1, tzinfo=UTC)
# Closes rise by exactly 1 per day: 100, 101, 102, ..., 109 -- forward returns are
# easy to hand-verify without relying on the code under test to compute them.
CLOSES = [Decimal(100 + i) for i in range(10)]


def _candles() -> tuple[Candle, ...]:
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
        for i, close in enumerate(CLOSES)
    )


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


def _expected_return(index: int, forward_days: int) -> float:
    entry = CLOSES[index]
    exit_ = CLOSES[index + forward_days]
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
        expected_avg = (_expected_return(0, 3) + _expected_return(5, 3)) / 2
        assert result.average_forward_return_pct == pytest.approx(expected_avg)

    def test_bearish_miss_when_forward_return_positive(self) -> None:
        """Prices rise every day in this fixture -- a BEARISH pattern implies a fall,
        so every occurrence here is a miss, not a hit."""
        candles = _candles()
        patterns = (_pattern("TESTDOWN", PatternDirection.BEARISH, 1, candles),)
        (result,) = historical_performance(candles, patterns, forward_days=3)
        assert result.occurrences == 1
        assert result.hit_rate == pytest.approx(0.0)
        assert result.average_forward_return_pct == pytest.approx(_expected_return(1, 3))

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

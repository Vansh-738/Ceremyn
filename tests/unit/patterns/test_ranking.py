from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ceremyn.domain import Candle, Pattern, TimeFrame
from ceremyn.domain.enums import AssetClass, PatternDirection
from ceremyn.patterns import ranking


def market() -> tuple[tuple[Candle, ...], tuple[Pattern, ...]]:
    candles = tuple(
        Candle(
            tradingsymbol="TEST",
            timeframe=TimeFrame.DAY,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=Decimal(100 + i % 2 * 2),
            high=Decimal(103),
            low=Decimal(99),
            close=Decimal(100 + i % 2 * 2),
            volume=1000,
        )
        for i in range(101)
    )
    patterns = tuple(
        Pattern(
            name="alternation",
            source="fixture",
            tradingsymbol="TEST",
            detected_at=c.timestamp,
            direction=PatternDirection.BULLISH,
        )
        for i, c in enumerate(candles)
        if i % 2 == 0
    )
    return candles, patterns


def test_nonoverlap_and_unobserved_future_are_excluded() -> None:
    assert ranking.deoverlap([0, 1, 2, 3, 3, 6], 3) == [0, 3, 6]
    candles, patterns = market()
    measured = ranking.evidence(candles, patterns, PatternDirection.BULLISH, 1)
    assert measured.occurrences == 50
    assert measured.hit_rate == 1 and measured.baseline_hit_rate == 0.5
    assert measured.excess_return > 0 and measured.p_value < 0.001
    with pytest.raises(ValueError):
        ranking.deoverlap([0], 0)


def test_holdout_is_purged_and_flat_is_not_bearish_success() -> None:
    candles, patterns = market()
    half = ranking.evidence(candles, patterns, PatternDirection.BULLISH, 3, 0, 50)
    assert half.occurrences == 12
    flat = tuple(c.model_copy(update={"close": Decimal(100)}) for c in candles)
    assert ranking.evidence(flat, patterns, PatternDirection.BEARISH, 1).hit_rate == 0


def test_scan_wide_significance_and_fundamental_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    candles, patterns = market()
    monkeypatch.setattr(ranking, "detect_patterns", lambda cs, symbol: patterns)
    results = ranking.find_ranked_opportunities(
        {"TEST": candles}, {"TEST": AssetClass.EQUITY}, forward_days=1, min_occurrences=10
    )
    assert len(results) == 1
    assert results[0].hit_rate_lift == 0.5
    assert results[0].adjusted_p_value < 0.01
    assert results[0].research_use == "long_candidate"
    assert (
        ranking.find_ranked_opportunities(
            {"TEST": candles}, {}, forward_days=1, require_fundamentals=True
        )
        == ()
    )
    # A high unconditional success rate is not edge.
    rising = tuple(c.model_copy(update={"close": Decimal(100 + i)}) for i, c in enumerate(candles))
    assert ranking.find_ranked_opportunities({"TEST": rising}, {}, forward_days=1) == ()


def test_inactive_hypotheses_are_included_in_fdr(monkeypatch: pytest.MonkeyPatch) -> None:
    candles, patterns = market()
    inactive = tuple(p.model_copy(update={"name": "inactive"}) for p in patterns[:-1])
    monkeypatch.setattr(ranking, "detect_patterns", lambda cs, symbol: patterns + inactive)
    original = ranking.false_discovery_control
    seen = []

    def corrected(values, **kwargs):
        seen.append(len(values))
        return original(values, **kwargs)

    monkeypatch.setattr(ranking, "false_discovery_control", corrected)
    assert len(ranking.find_ranked_opportunities({"TEST": candles}, {}, forward_days=1)) == 1
    assert seen == [2]

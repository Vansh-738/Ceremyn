import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ceremyn.domain import Candle, TimeFrame
from ceremyn.domain.enums import AssetClass, PatternDirection
from ceremyn.patterns import find_opportunities

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(symbol: str, i: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(
        tradingsymbol=symbol,
        timeframe=TimeFrame.DAY,
        timestamp=START + timedelta(days=i),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
    )


def _oscillating(symbol: str, n: int, *, doji_every: int | None = None) -> tuple[Candle, ...]:
    """A deterministic sine-wave series (see test_candlestick.py for why the
    lookback filler is needed) with an obvious Doji forced every `doji_every`
    bars -- including the last one -- so historical occurrences accumulate
    while the latest bar is always itself an occurrence."""
    candles = []
    for i in range(n):
        base = 100 + math.sin(i / 2.0) * 3
        o, c = base, base + 0.3
        h, low = max(o, c) + 1.0, min(o, c) - 1.0
        if doji_every and i % doji_every == doji_every - 1:
            o, c, h, low = 100.0, 100.02, 108.0, 92.0
        candles.append(_candle(symbol, i, o, h, low, c))
    return tuple(candles)


class TestFindOpportunities:
    def test_plain_series_yields_no_opportunities(self) -> None:
        candles = _oscillating("PLAIN", 30)
        opportunities = find_opportunities({"PLAIN": candles}, {"PLAIN": AssetClass.EQUITY})
        assert opportunities == ()

    def test_recurring_pattern_at_latest_bar_is_surfaced(self) -> None:
        candles = _oscillating("TEST", 60, doji_every=5)
        opportunities = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10
        )
        assert len(opportunities) > 0
        doji = next(o for o in opportunities if o.pattern_name == "DOJI")
        assert doji.tradingsymbol == "TEST"
        assert doji.asset_class is AssetClass.EQUITY
        assert doji.direction is PatternDirection.BULLISH
        assert doji.detected_at == candles[-1].timestamp
        assert doji.occurrences == 50
        assert 0.0 <= doji.hit_rate <= 1.0

    def test_results_sorted_by_edge_score_descending(self) -> None:
        candles = _oscillating("TEST", 60, doji_every=5)
        opportunities = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10
        )
        scores = [o.edge_score for o in opportunities]
        assert scores == sorted(scores, reverse=True)

    def test_min_occurrences_filters_low_evidence_patterns(self) -> None:
        candles = _oscillating("TEST", 60, doji_every=5)
        loose = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10
        )
        strict = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=30
        )
        assert len(strict) < len(loose)
        assert all(o.occurrences >= 30 for o in strict)

    def test_too_few_candles_excluded(self) -> None:
        candles = _oscillating("SHORT", 10, doji_every=5)
        opportunities = find_opportunities(
            {"SHORT": candles}, {"SHORT": AssetClass.EQUITY}, min_occurrences=1
        )
        assert opportunities == ()

    def test_multiple_symbols_and_asset_classes_combined_and_ranked_together(self) -> None:
        equity = _oscillating("RELIANCE", 60, doji_every=5)
        commodity = _oscillating("CRUDEOIL", 30)  # contributes nothing (plain series)
        opportunities = find_opportunities(
            {"RELIANCE": equity, "CRUDEOIL": commodity},
            {"RELIANCE": AssetClass.EQUITY, "CRUDEOIL": AssetClass.COMMODITY},
            min_occurrences=10,
        )
        assert len(opportunities) > 0
        assert all(o.tradingsymbol == "RELIANCE" for o in opportunities)
        assert all(o.asset_class is AssetClass.EQUITY for o in opportunities)

    def test_unknown_symbol_defaults_asset_class_to_equity(self) -> None:
        candles = _oscillating("MYSTERY", 60, doji_every=5)
        opportunities = find_opportunities({"MYSTERY": candles}, {}, min_occurrences=10)
        assert len(opportunities) > 0
        assert all(o.asset_class is AssetClass.EQUITY for o in opportunities)

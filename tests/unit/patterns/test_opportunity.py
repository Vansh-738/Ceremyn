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
        # min_hit_rate=0.0 isolates "did the latest-bar mechanic surface DOJI at
        # all" from the separate hit-rate-quality filter tested below -- DOJI's
        # own real hit rate here (~0.42) is below the default 0.5 quality bar.
        opportunities = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10, min_hit_rate=0.0
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
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10, min_hit_rate=0.0
        )
        scores = [o.edge_score for o in opportunities]
        assert scores == sorted(scores, reverse=True)

    def test_min_occurrences_filters_low_evidence_patterns(self) -> None:
        candles = _oscillating("TEST", 60, doji_every=5)
        loose = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10, min_hit_rate=0.0
        )
        strict = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=30, min_hit_rate=0.0
        )
        assert len(strict) < len(loose)
        assert all(o.occurrences >= 30 for o in strict)

    def test_min_hit_rate_excludes_patterns_no_better_than_a_coin_flip(self) -> None:
        """A large average move must never make up for an unreliable hit rate --
        the real fixture here has DOJI at ~42% (below chance) and DOJISTAR at
        ~56% (above chance); only DOJISTAR should survive the default filter."""
        candles = _oscillating("TEST", 60, doji_every=5)
        loose = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10, min_hit_rate=0.0
        )
        strict = find_opportunities(
            {"TEST": candles}, {"TEST": AssetClass.EQUITY}, min_occurrences=10
        )
        assert any(o.pattern_name == "DOJI" for o in loose)
        assert all(o.hit_rate > 0.5 for o in strict)
        assert not any(o.pattern_name == "DOJI" for o in strict)
        assert len(strict) < len(loose)

    def test_too_few_candles_excluded(self) -> None:
        candles = _oscillating("SHORT", 10, doji_every=5)
        opportunities = find_opportunities(
            {"SHORT": candles}, {"SHORT": AssetClass.EQUITY}, min_occurrences=1, min_hit_rate=0.0
        )
        assert opportunities == ()

    def test_stale_symbol_excluded_even_if_otherwise_qualifying(self) -> None:
        """A thinly-traded/suspended symbol whose own last bar is weeks behind the
        rest of the scan must not be surfaced as if it were a live opportunity --
        regression for a real symbol (RSSOFTWARE) whose last bhavcopy appearance
        was ~3.5 months before the scan's newest bar getting ranked as "current"."""
        fresh = _oscillating("FRESH", 60, doji_every=5)
        stale = _oscillating("STALE", 40, doji_every=5)  # last bar 20 days behind FRESH
        opportunities = find_opportunities(
            {"FRESH": fresh, "STALE": stale},
            {"FRESH": AssetClass.EQUITY, "STALE": AssetClass.EQUITY},
            min_occurrences=10,
            min_hit_rate=0.0,
        )
        assert any(o.tradingsymbol == "FRESH" for o in opportunities)
        assert not any(o.tradingsymbol == "STALE" for o in opportunities)

    def test_max_staleness_days_is_configurable(self) -> None:
        fresh = _oscillating("FRESH", 60, doji_every=5)
        stale = _oscillating("STALE", 40, doji_every=5)
        opportunities = find_opportunities(
            {"FRESH": fresh, "STALE": stale},
            {"FRESH": AssetClass.EQUITY, "STALE": AssetClass.EQUITY},
            min_occurrences=10,
            min_hit_rate=0.0,
            max_staleness_days=30,  # wide enough to include STALE's 20-day lag
        )
        assert any(o.tradingsymbol == "STALE" for o in opportunities)

    def test_multiple_symbols_and_asset_classes_combined_and_ranked_together(self) -> None:
        equity = _oscillating("RELIANCE", 60, doji_every=5)
        commodity = _oscillating("CRUDEOIL", 30)  # contributes nothing (plain series)
        opportunities = find_opportunities(
            {"RELIANCE": equity, "CRUDEOIL": commodity},
            {"RELIANCE": AssetClass.EQUITY, "CRUDEOIL": AssetClass.COMMODITY},
            min_occurrences=10,
            min_hit_rate=0.0,
        )
        assert len(opportunities) > 0
        assert all(o.tradingsymbol == "RELIANCE" for o in opportunities)
        assert all(o.asset_class is AssetClass.EQUITY for o in opportunities)

    def test_unknown_symbol_defaults_asset_class_to_equity(self) -> None:
        candles = _oscillating("MYSTERY", 60, doji_every=5)
        opportunities = find_opportunities(
            {"MYSTERY": candles}, {}, min_occurrences=10, min_hit_rate=0.0
        )
        assert len(opportunities) > 0
        assert all(o.asset_class is AssetClass.EQUITY for o in opportunities)

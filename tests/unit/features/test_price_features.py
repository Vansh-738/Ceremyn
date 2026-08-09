import pytest

from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.price_features import MarketRegime
from ceremyn.features.registry import default_registry
from tests.unit.features.conftest import make_context, trending_closes


def value(name: str, ctx: FeatureContext) -> FeatureScalar:
    return default_registry.get(name).evaluate(ctx)


def ctx_with(closes: list[float]) -> FeatureContext:
    return make_context(closes=closes)


class TestComputability:
    def test_price_features_none_without_enough_candles(self) -> None:
        ctx = ctx_with(trending_closes(5))  # too few for most windows
        for name in (
            "atr_14",
            "ema_21",
            "rsi_14",
            "adx_14",
            "historical_volatility_20",
            "realized_volatility_20",
            "market_regime",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "bollinger_percent_b",
            "bollinger_bandwidth",
            "stochastic_k",
            "stochastic_d",
        ):
            assert value(name, ctx) is None

    def test_vwap_needs_only_one_candle(self) -> None:
        assert value("vwap", ctx_with(trending_closes(1))) is not None


class TestValues:
    def test_ema_and_rsi_on_uptrend(self) -> None:
        ctx = ctx_with(trending_closes(40))
        ema = value("ema_21", ctx)
        rsi = value("rsi_14", ctx)
        assert isinstance(ema, float) and ema > 0.0
        assert rsi == 100.0  # pure uptrend

    def test_atr_positive(self) -> None:
        atr = value("atr_14", ctx_with(trending_closes(40)))
        assert isinstance(atr, float) and atr > 0.0

    def test_adx_bounded(self) -> None:
        adx = value("adx_14", ctx_with(trending_closes(40)))
        assert isinstance(adx, float) and 0.0 <= adx <= 100.0

    def test_trend_strength_high_on_line(self) -> None:
        ts = value("trend_strength", ctx_with(trending_closes(40)))
        assert isinstance(ts, float) and ts > 95.0  # near-perfect linear fit

    def test_volatilities_non_negative(self) -> None:
        ctx = ctx_with(trending_closes(40))
        hv = value("historical_volatility_20", ctx)
        rv = value("realized_volatility_20", ctx)
        assert isinstance(hv, float) and hv >= 0.0
        assert isinstance(rv, float) and rv >= 0.0

    def test_macd_positive_on_sustained_uptrend(self) -> None:
        ctx = ctx_with(trending_closes(60))
        line = value("macd_line", ctx)
        signal = value("macd_signal", ctx)
        histogram = value("macd_histogram", ctx)
        assert isinstance(line, float) and line > 0.0  # fast EMA pulls ahead of slow EMA
        assert isinstance(signal, float)
        assert isinstance(histogram, float)
        assert histogram == pytest.approx(line - signal)

    def test_bollinger_percent_b_and_bandwidth_on_uptrend(self) -> None:
        ctx = ctx_with(trending_closes(40))
        pct_b = value("bollinger_percent_b", ctx)
        bandwidth = value("bollinger_bandwidth", ctx)
        assert isinstance(pct_b, float) and pct_b > 0.5  # price sits above the rolling mean
        assert isinstance(bandwidth, float) and bandwidth > 0.0

    def test_stochastic_k_and_d_near_period_high_on_pure_uptrend(self) -> None:
        ctx = ctx_with(trending_closes(40))
        k = value("stochastic_k", ctx)
        d = value("stochastic_d", ctx)
        # Strictly rising closes with a fixed +/-1 high/low band around each bar: close
        # sits near (not exactly at) the period high, since the band adds slack.
        assert isinstance(k, float) and 80.0 < k <= 100.0
        assert isinstance(d, float) and 80.0 < d <= 100.0


class TestMarketRegime:
    def test_trending_on_strong_line(self) -> None:
        regime = value("market_regime", ctx_with(trending_closes(40)))
        assert regime == MarketRegime.TRENDING.value

    def test_range_bound_on_flat_noise(self) -> None:
        # Low trend R^2 and low volatility -> range-bound.
        closes = [100.0 + (0.05 if i % 2 else -0.05) for i in range(40)]
        assert value("market_regime", ctx_with(closes)) == MarketRegime.RANGE_BOUND.value

    def test_high_volatility_regime(self) -> None:
        # Big alternating swings: low trend R^2 but high realized volatility.
        closes = [100.0 + (8.0 if i % 2 else -8.0) for i in range(40)]
        assert value("market_regime", ctx_with(closes)) == MarketRegime.HIGH_VOLATILITY.value

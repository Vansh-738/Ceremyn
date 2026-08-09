"""Price and volatility features over the underlying candle history.

Thin wrappers over the pure kernels in ``indicators.py``. Default periods are encoded
in each feature's name (e.g. ``ema_21``) so alternative configurations never collide
in the cache.
"""

from enum import StrEnum

from ceremyn.features import indicators
from ceremyn.features.base import Feature
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.registry import register

EMA_PERIOD = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
VOL_WINDOW = 20
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BOLLINGER_PERIOD = 20
BOLLINGER_NUM_STD = 2.0
STOCHASTIC_K_PERIOD = 14
STOCHASTIC_D_PERIOD = 3


class MarketRegime(StrEnum):
    TRENDING = "trending"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"


@register
class VWAPFeature(Feature):
    name = "vwap"
    min_candles = 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.vwap(ctx.highs, ctx.lows, ctx.closes, ctx.volumes)


@register
class ATRFeature(Feature):
    name = "atr_14"
    min_candles = ATR_PERIOD + 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.atr(ctx.highs, ctx.lows, ctx.closes, period=ATR_PERIOD)


@register
class EMAFeature(Feature):
    name = "ema_21"
    min_candles = EMA_PERIOD

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.ema(ctx.closes, period=EMA_PERIOD)


@register
class RSIFeature(Feature):
    name = "rsi_14"
    min_candles = RSI_PERIOD + 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.rsi(ctx.closes, period=RSI_PERIOD)


@register
class ADXFeature(Feature):
    name = "adx_14"
    min_candles = 2 * ADX_PERIOD + 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.adx(ctx.highs, ctx.lows, ctx.closes, period=ADX_PERIOD)


@register
class MACDLineFeature(Feature):
    """MACD line = fast EMA - slow EMA of closes. A cross above 0 (the
    centerline) signals a longer-term regime change to bullish momentum."""

    name = "macd_line"
    min_candles = MACD_SLOW + MACD_SIGNAL

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        result = indicators.macd(
            ctx.closes, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        return result[0] if result is not None else None


@register
class MACDSignalFeature(Feature):
    """Signal line = EMA of the MACD line itself."""

    name = "macd_signal"
    min_candles = MACD_SLOW + MACD_SIGNAL

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        result = indicators.macd(
            ctx.closes, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        return result[1] if result is not None else None


@register
class MACDHistogramFeature(Feature):
    """Histogram = MACD line - signal line. A sign flip is the classic
    signal-line-crossover momentum trigger (faster than the centerline cross)."""

    name = "macd_histogram"
    min_candles = MACD_SLOW + MACD_SIGNAL

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        result = indicators.macd(
            ctx.closes, fast_period=MACD_FAST, slow_period=MACD_SLOW, signal_period=MACD_SIGNAL
        )
        return result[2] if result is not None else None


@register
class BollingerPercentBFeature(Feature):
    """%B: where price sits relative to the Bollinger Bands, normalized so 0 =
    the lower band, 1 = the upper band -- a single-float input for downstream
    models. Deliberately allowed outside [0, 1] on a real band breakout."""

    name = "bollinger_percent_b"
    min_candles = BOLLINGER_PERIOD

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.bollinger_percent_b(
            ctx.closes, period=BOLLINGER_PERIOD, num_std=BOLLINGER_NUM_STD
        )


@register
class BollingerBandwidthFeature(Feature):
    """Normalized Bollinger band width. A falling bandwidth is the classic
    volatility "squeeze" that often precedes an explosive breakout."""

    name = "bollinger_bandwidth"
    min_candles = BOLLINGER_PERIOD

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.bollinger_bandwidth(
            ctx.closes, period=BOLLINGER_PERIOD, num_std=BOLLINGER_NUM_STD
        )


@register
class StochasticKFeature(Feature):
    """%K: today's close positioned within the recent high/low range, in
    [0, 100]. Reacts faster to swings than RSI; most reliable in a ranging
    market (pair with a low ADX reading)."""

    name = "stochastic_k"
    min_candles = STOCHASTIC_K_PERIOD + STOCHASTIC_D_PERIOD - 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        result = indicators.stochastic(
            ctx.highs,
            ctx.lows,
            ctx.closes,
            k_period=STOCHASTIC_K_PERIOD,
            d_period=STOCHASTIC_D_PERIOD,
        )
        return result[0] if result is not None else None


@register
class StochasticDFeature(Feature):
    """%D: a smoothed (SMA) version of %K, in [0, 100]."""

    name = "stochastic_d"
    min_candles = STOCHASTIC_K_PERIOD + STOCHASTIC_D_PERIOD - 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        result = indicators.stochastic(
            ctx.highs,
            ctx.lows,
            ctx.closes,
            k_period=STOCHASTIC_K_PERIOD,
            d_period=STOCHASTIC_D_PERIOD,
        )
        return result[1] if result is not None else None


@register
class HistoricalVolatilityFeature(Feature):
    name = "historical_volatility_20"
    min_candles = VOL_WINDOW + 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.historical_volatility(ctx.closes, window=VOL_WINDOW)


@register
class RealizedVolatilityFeature(Feature):
    name = "realized_volatility_20"
    min_candles = VOL_WINDOW + 1

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return indicators.realized_volatility(ctx.closes, window=VOL_WINDOW)


@register
class TrendStrengthFeature(Feature):
    """0..100 trend strength = R^2 of a linear fit of closes; direction in metadata."""

    name = "trend_strength"
    min_candles = 2

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        fit = indicators.linreg_r2_slope(ctx.closes)
        if fit is None:
            return None
        _slope, r_squared = fit
        return round(r_squared * 100.0, 4)


@register
class MarketRegimeFeature(Feature):
    """Classify the regime from trend strength and historical volatility."""

    name = "market_regime"
    min_candles = VOL_WINDOW + 1

    TREND_THRESHOLD = 40.0  # trend_strength (R^2 * 100) at/above which we call it trending
    HIGH_VOL_THRESHOLD = 0.30  # annualized HV at/above which we call it high-volatility

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        fit = indicators.linreg_r2_slope(ctx.closes)
        trend = (fit[1] * 100.0) if fit is not None else 0.0
        hv = indicators.historical_volatility(ctx.closes, window=VOL_WINDOW)
        if trend >= self.TREND_THRESHOLD:
            return MarketRegime.TRENDING.value
        if hv is not None and hv >= self.HIGH_VOL_THRESHOLD:
            return MarketRegime.HIGH_VOLATILITY.value
        return MarketRegime.RANGE_BOUND.value

"""Price and volatility features over the underlying candle history.

Thin wrappers over the pure kernels in ``indicators.py``. Default periods are encoded
in each feature's name (e.g. ``ema_21``) so alternative configurations never collide
in the cache.
"""

from enum import StrEnum

from alphaquant.features import indicators
from alphaquant.features.base import Feature
from alphaquant.features.context import FeatureContext
from alphaquant.features.models import FeatureScalar
from alphaquant.features.registry import register

EMA_PERIOD = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
VOL_WINDOW = 20


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

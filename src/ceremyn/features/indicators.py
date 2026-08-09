"""Pure numeric indicator kernels (the NumPy boundary).

Floats by design: these are numerical analytics, not money. Every function is a
deterministic pure function of its input arrays — no I/O, no clocks, no state. All
return None when there is insufficient data, so callers never see a partial value.

Volatility figures are annualized with a configurable number of periods per year
(``periods_per_year``); for daily candles use 252, for intraday bars scale accordingly.
"""

from typing import Any

import numpy as np

TRADING_DAYS = 252

FloatArray = np.ndarray[Any, Any]


def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average (final value); None if fewer than `period` points."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    arr = np.asarray(values, dtype=float)
    alpha = 2.0 / (period + 1.0)
    # Seed with the SMA of the first `period` values, then walk the EMA forward.
    result = float(arr[:period].mean())
    for value in arr[period:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI in [0, 100]; None if fewer than `period + 1` closes."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(closes) < period + 1:
        return None
    deltas = np.diff(np.asarray(closes, dtype=float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + float(gain)) / period
        avg_loss = (avg_loss * (period - 1) + float(loss)) / period
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """Per-bar true range; length == len(highs) (first bar uses high-low)."""
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    close = np.asarray(closes, dtype=float)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    return [float(value) for value in tr]


def atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """Average true range (Wilder smoothing); None if fewer than `period + 1` bars."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(highs) < period + 1:
        return None
    tr = true_range(highs, lows, closes)[1:]  # drop the seed bar's degenerate TR
    smoothed = float(np.asarray(tr[:period], dtype=float).mean())
    for value in tr[period:]:
        smoothed = (smoothed * (period - 1) + value) / period
    return smoothed


def adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """Average directional index in [0, 100]; None if insufficient data."""
    if period <= 0:
        raise ValueError("period must be positive")
    if len(highs) < 2 * period + 1:
        return None
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.asarray(true_range(highs, lows, closes)[1:], dtype=float)

    plus_di = _wilder_di(plus_dm, tr, period)
    minus_di = _wilder_di(minus_dm, tr, period)
    denom = plus_di + minus_di
    dx = np.where(
        denom == 0.0, 0.0, np.abs(plus_di - minus_di) / np.where(denom == 0, 1, denom) * 100.0
    )
    if len(dx) < period:
        return None
    return float(np.asarray(dx[-period:], dtype=float).mean())


def _wilder_di(dm: FloatArray, tr: FloatArray, period: int) -> FloatArray:
    """Wilder-smoothed directional indicator series aligned to `tr`."""
    smoothed_dm = _wilder_smooth(dm, period)
    smoothed_tr = _wilder_smooth(tr, period)
    safe_tr = np.where(smoothed_tr == 0, 1, smoothed_tr)
    return np.where(smoothed_tr == 0.0, 0.0, smoothed_dm / safe_tr * 100.0)


def _wilder_smooth(values: FloatArray, period: int) -> FloatArray:
    out = np.zeros(len(values))
    if len(values) < period:
        return out
    out[period - 1] = values[:period].sum()
    for i in range(period, len(values)):
        out[i] = out[i - 1] - out[i - 1] / period + values[i]
    return out


def _ema_series(values: FloatArray, period: int) -> FloatArray:
    """Full EMA series (not just the final value, unlike `ema()`), seeded with the
    SMA of the first `period` values -- the same seeding convention `ema()` uses.
    Output length is `len(values) - period + 1`."""
    alpha = 2.0 / (period + 1.0)
    out = np.empty(len(values) - period + 1)
    out[0] = values[:period].mean()
    for i, value in enumerate(values[period:], start=1):
        out[i] = alpha * float(value) + (1.0 - alpha) * out[i - 1]
    return out


def macd(
    closes: list[float],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> tuple[float, float, float] | None:
    """MACD line, signal line, and histogram (line - signal); final values only.

    MACD line = fast EMA - slow EMA of closes; signal line = EMA of the MACD line
    itself. None if there isn't enough history for the slow EMA and the signal
    EMA on top of it to both be seeded.
    """
    if fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        raise ValueError("periods must be positive")
    if slow_period <= fast_period:
        raise ValueError("slow_period must exceed fast_period")
    arr = np.asarray(closes, dtype=float)
    if len(arr) < slow_period + signal_period:
        return None
    fast_ema = _ema_series(arr, fast_period)
    slow_ema = _ema_series(arr, slow_period)
    # fast_ema starts earlier (shorter period) than slow_ema; align them to the
    # same time index before subtracting.
    aligned_fast = fast_ema[slow_period - fast_period :]
    macd_line_series = aligned_fast - slow_ema
    signal_series = _ema_series(macd_line_series, signal_period)
    macd_line = float(macd_line_series[-1])
    signal_line = float(signal_series[-1])
    return macd_line, signal_line, macd_line - signal_line


def bollinger_percent_b(
    closes: list[float], *, period: int = 20, num_std: float = 2.0
) -> float | None:
    """%B: where the latest close sits relative to the Bollinger Bands,
    (close - lower) / (upper - lower). 0 = at the lower band, 1 = at the upper
    band; deliberately allowed outside [0, 1] when price breaks through a band
    -- that overextension is a real signal, not an error. None if fewer than
    `period` closes."""
    if period <= 1:
        raise ValueError("period must be > 1")
    if len(closes) < period:
        return None
    window = np.asarray(closes[-period:], dtype=float)
    middle = float(window.mean())
    std = float(window.std(ddof=0))
    upper, lower = middle + num_std * std, middle - num_std * std
    if upper == lower:
        return 0.5  # zero-volatility window: price is exactly at the flat bands
    return float((closes[-1] - lower) / (upper - lower))


def bollinger_bandwidth(
    closes: list[float], *, period: int = 20, num_std: float = 2.0
) -> float | None:
    """Normalized band width: (upper - lower) / middle. A falling bandwidth
    signals a developing "squeeze" -- tightening volatility that often precedes
    a breakout. None if fewer than `period` closes or a zero-price window."""
    if period <= 1:
        raise ValueError("period must be > 1")
    if len(closes) < period:
        return None
    window = np.asarray(closes[-period:], dtype=float)
    middle = float(window.mean())
    if middle == 0.0:
        return None
    std = float(window.std(ddof=0))
    return float((2.0 * num_std * std) / middle)


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    *,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[float, float] | None:
    """%K and %D (a `d_period`-bar SMA of %K), both in [0, 100]. None if fewer
    than `k_period + d_period - 1` bars."""
    if k_period <= 0 or d_period <= 0:
        raise ValueError("periods must be positive")
    if len(closes) < k_period + d_period - 1:
        return None
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    close = np.asarray(closes, dtype=float)
    k_values: list[float] = []
    for i in range(k_period - 1, len(close)):
        window_high = float(high[i - k_period + 1 : i + 1].max())
        window_low = float(low[i - k_period + 1 : i + 1].min())
        span = window_high - window_low
        k_values.append(50.0 if span == 0.0 else float((close[i] - window_low) / span * 100.0))
    percent_k = k_values[-1]
    percent_d = float(np.mean(k_values[-d_period:]))
    return percent_k, percent_d


def vwap(
    highs: list[float], lows: list[float], closes: list[float], volumes: list[float]
) -> float | None:
    """Volume-weighted average price over the given bars; None if no volume."""
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    close = np.asarray(closes, dtype=float)
    volume = np.asarray(volumes, dtype=float)
    total_volume = float(volume.sum())
    if total_volume <= 0.0:
        return None
    typical = (high + low + close) / 3.0
    return float((typical * volume).sum() / total_volume)


def log_returns(closes: list[float]) -> FloatArray:
    arr = np.asarray(closes, dtype=float)
    if len(arr) < 2 or np.any(arr <= 0):
        return np.array([], dtype=float)
    return np.diff(np.log(arr))


def historical_volatility(
    closes: list[float], *, window: int = 20, periods_per_year: int = TRADING_DAYS
) -> float | None:
    """Annualized close-to-close volatility (sample std of log returns) over `window`."""
    if window < 2:
        raise ValueError("window must be >= 2")
    returns = log_returns(closes)
    if len(returns) < window:
        return None
    recent = returns[-window:]
    return float(recent.std(ddof=1) * np.sqrt(periods_per_year))


def realized_volatility(
    closes: list[float], *, window: int = 20, periods_per_year: int = TRADING_DAYS
) -> float | None:
    """Annualized realized volatility: RMS of log returns (not mean-centered)."""
    if window < 1:
        raise ValueError("window must be >= 1")
    returns = log_returns(closes)
    if len(returns) < window:
        return None
    recent = returns[-window:]
    return float(np.sqrt(np.mean(np.square(recent)) * periods_per_year))


def linreg_r2_slope(values: list[float]) -> tuple[float, float] | None:
    """Ordinary-least-squares fit of `values` vs index: returns (slope, r_squared).

    r_squared is in [0, 1]; slope carries the trend direction. None if < 2 points or
    the series is constant (undefined fit quality).
    """
    if len(values) < 2:
        return None
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot == 0.0:
        return None
    r_squared = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return float(slope), r_squared

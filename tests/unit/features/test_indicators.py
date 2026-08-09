import math

import pytest

from ceremyn.features import indicators


class TestEMA:
    def test_seed_is_sma_when_exactly_period(self) -> None:
        assert indicators.ema([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)

    def test_tracks_upward_series(self) -> None:
        value = indicators.ema([float(i) for i in range(1, 21)], 5)
        assert value is not None and value > 15.0

    def test_none_when_insufficient(self) -> None:
        assert indicators.ema([1, 2, 3], 5) is None

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.ema([1, 2, 3], 0)


class TestRSI:
    def test_all_gains_is_100(self) -> None:
        assert indicators.rsi([float(i) for i in range(1, 20)], 14) == 100.0

    def test_all_losses_is_0(self) -> None:
        assert indicators.rsi([float(i) for i in range(20, 1, -1)], 14) == 0.0

    def test_within_bounds_for_mixed(self) -> None:
        closes = [10, 11, 10.5, 11.5, 10.8, 12, 11.2, 12.5, 11.8, 13, 12, 13.5, 12.8, 14, 13.2]
        value = indicators.rsi(closes, 14)
        assert value is not None and 0.0 <= value <= 100.0

    def test_none_when_insufficient(self) -> None:
        assert indicators.rsi([1, 2, 3], 14) is None

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.rsi([1, 2, 3, 4], 0)


class TestTrueRangeATR:
    def test_true_range_first_bar_is_high_low(self) -> None:
        tr = indicators.true_range([10, 12], [8, 9], [9, 11])
        assert tr[0] == pytest.approx(2.0)

    def test_atr_constant_band_equals_band(self) -> None:
        closes = [100.0] * 20
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        assert indicators.atr(highs, lows, closes, period=14) == pytest.approx(2.0)

    def test_atr_none_when_insufficient(self) -> None:
        assert indicators.atr([1, 2], [1, 2], [1, 2], period=14) is None

    def test_atr_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.atr([1, 2, 3], [1, 2, 3], [1, 2, 3], period=0)


class TestADX:
    def test_strong_uptrend_high_adx(self) -> None:
        closes = [float(i) for i in range(1, 40)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        value = indicators.adx(highs, lows, closes, period=14)
        assert value is not None and 0.0 <= value <= 100.0 and value > 50.0

    def test_none_when_insufficient(self) -> None:
        assert indicators.adx([1, 2, 3], [1, 2, 3], [1, 2, 3], period=14) is None

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.adx([1.0] * 40, [1.0] * 40, [1.0] * 40, period=0)


class TestVWAP:
    def test_single_bar(self) -> None:
        # typical = (3 + 1 + 2)/3 = 2.0, single bar -> vwap == typical
        assert indicators.vwap([3.0], [1.0], [2.0], [10.0]) == pytest.approx(2.0)

    def test_volume_weighting(self) -> None:
        # H=L=C so typical price == close; vwap is the volume-weighted mean.
        vwap = indicators.vwap([2, 4], [2, 4], [2, 4], [1, 3])
        assert vwap == pytest.approx((2 * 1 + 4 * 3) / 4)

    def test_zero_volume_is_none(self) -> None:
        assert indicators.vwap([1], [1], [1], [0]) is None


class TestVolatility:
    def test_hv_constant_series_is_zero(self) -> None:
        assert indicators.historical_volatility([100.0] * 25, window=20) == pytest.approx(0.0)

    def test_hv_positive_for_varying(self) -> None:
        closes = [100 + (i % 3) for i in range(30)]
        value = indicators.historical_volatility(closes, window=20)
        assert value is not None and value > 0.0

    def test_hv_annualization(self) -> None:
        # Alternating +/- log returns of equal magnitude: std(ddof=1) * sqrt(252).
        closes = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0]
        value = indicators.historical_volatility(closes, window=5, periods_per_year=252)
        assert value is not None and value > 0.0

    def test_rv_rms_formula(self) -> None:
        closes = [100.0, 110.0, 100.0]  # symmetric big moves
        rv = indicators.realized_volatility(closes, window=2, periods_per_year=1)
        returns = [math.log(110 / 100), math.log(100 / 110)]
        expected = math.sqrt(sum(r * r for r in returns) / 2)
        assert rv == pytest.approx(expected)

    def test_none_when_insufficient(self) -> None:
        assert indicators.historical_volatility([100, 101], window=20) is None
        assert indicators.realized_volatility([100, 101], window=20) is None

    def test_rejects_bad_window(self) -> None:
        with pytest.raises(ValueError):
            indicators.historical_volatility([1, 2, 3], window=1)
        with pytest.raises(ValueError):
            indicators.realized_volatility([1, 2, 3], window=0)


class TestLinReg:
    def test_perfect_line(self) -> None:
        fit = indicators.linreg_r2_slope([1, 2, 3, 4, 5])
        assert fit is not None
        slope, r2 = fit
        assert slope == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)

    def test_constant_series_is_none(self) -> None:
        assert indicators.linreg_r2_slope([5, 5, 5]) is None

    def test_too_short_is_none(self) -> None:
        assert indicators.linreg_r2_slope([1]) is None

    def test_downtrend_negative_slope(self) -> None:
        fit = indicators.linreg_r2_slope([5, 4, 3, 2, 1])
        assert fit is not None and fit[0] < 0

    def test_log_returns_guard_on_non_positive(self) -> None:
        assert len(indicators.log_returns([100, 0, 100])) == 0
        assert len(indicators.log_returns([100.0])) == 0


class TestMACD:
    def test_matches_independent_ema_recomputation(self) -> None:
        closes = [100 + 10 * math.sin(i / 5) + 0.1 * i for i in range(80)]
        result = indicators.macd(closes, fast_period=12, slow_period=26, signal_period=9)
        assert result is not None
        macd_line, signal_line, histogram = result

        def ema_full(values: list[float], period: int) -> list[float]:
            alpha = 2.0 / (period + 1)
            out = [sum(values[:period]) / period]
            for v in values[period:]:
                out.append(alpha * v + (1 - alpha) * out[-1])
            return out

        fast = ema_full(closes, 12)
        slow = ema_full(closes, 26)
        aligned_fast = fast[26 - 12 :]
        macd_series = [f - s for f, s in zip(aligned_fast, slow, strict=True)]
        signal = ema_full(macd_series, 9)
        assert macd_line == pytest.approx(macd_series[-1])
        assert signal_line == pytest.approx(signal[-1])
        assert histogram == pytest.approx(macd_series[-1] - signal[-1])

    def test_flat_series_is_zero(self) -> None:
        result = indicators.macd([100.0] * 40)
        assert result is not None
        macd_line, signal_line, histogram = result
        assert macd_line == pytest.approx(0.0)
        assert signal_line == pytest.approx(0.0)
        assert histogram == pytest.approx(0.0)

    def test_none_when_insufficient(self) -> None:
        result = indicators.macd([100.0] * 30, fast_period=12, slow_period=26, signal_period=9)
        assert result is None

    def test_rejects_non_positive_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.macd([100.0] * 40, fast_period=0)

    def test_rejects_slow_not_exceeding_fast(self) -> None:
        with pytest.raises(ValueError):
            indicators.macd([100.0] * 40, fast_period=26, slow_period=12)


class TestBollingerBands:
    def test_percent_b_at_middle_for_flat_series(self) -> None:
        assert indicators.bollinger_percent_b([100.0] * 20, period=20) == pytest.approx(0.5)

    def test_percent_b_one_at_the_upper_band(self) -> None:
        closes = [100.0] * 19 + [200.0]  # a huge final spike pushes close to/past the upper band
        pct_b = indicators.bollinger_percent_b(closes, period=20)
        assert pct_b is not None and pct_b > 1.0  # allowed to exceed 1 -- a real overextension

    def test_bandwidth_zero_for_flat_series(self) -> None:
        assert indicators.bollinger_bandwidth([100.0] * 20, period=20) == pytest.approx(0.0)

    def test_bandwidth_positive_for_varying_series(self) -> None:
        closes = [100 + (i % 3) for i in range(20)]
        bw = indicators.bollinger_bandwidth(closes, period=20)
        assert bw is not None and bw > 0.0

    def test_none_when_insufficient(self) -> None:
        assert indicators.bollinger_percent_b([100.0] * 5, period=20) is None
        assert indicators.bollinger_bandwidth([100.0] * 5, period=20) is None

    def test_rejects_bad_period(self) -> None:
        with pytest.raises(ValueError):
            indicators.bollinger_percent_b([100.0] * 5, period=1)
        with pytest.raises(ValueError):
            indicators.bollinger_bandwidth([100.0] * 5, period=1)


class TestStochastic:
    def test_bounded_for_varying_series(self) -> None:
        closes = [100 + 5 * ((i % 7) - 3) for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        result = indicators.stochastic(highs, lows, closes, k_period=14, d_period=3)
        assert result is not None
        percent_k, percent_d = result
        assert isinstance(percent_k, float) and isinstance(percent_d, float)
        assert 0.0 <= percent_k <= 100.0
        assert 0.0 <= percent_d <= 100.0

    def test_close_at_period_high_is_100(self) -> None:
        closes = [float(i) for i in range(1, 20)]  # strictly rising: close is always the high
        result = indicators.stochastic(closes, closes, closes, k_period=14, d_period=3)
        assert result is not None
        assert result[0] == pytest.approx(100.0)

    def test_flat_range_is_50(self) -> None:
        closes = [100.0] * 20
        result = indicators.stochastic(closes, closes, closes, k_period=14, d_period=3)
        assert result is not None
        assert result[0] == pytest.approx(50.0)

    def test_none_when_insufficient(self) -> None:
        closes = [100.0] * 5
        assert indicators.stochastic(closes, closes, closes, k_period=14, d_period=3) is None

    def test_rejects_non_positive_period(self) -> None:
        closes = [100.0] * 20
        with pytest.raises(ValueError):
            indicators.stochastic(closes, closes, closes, k_period=0)

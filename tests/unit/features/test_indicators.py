import math

import pytest

from alphaquant.features import indicators


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

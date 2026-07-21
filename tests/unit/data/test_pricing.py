"""Pricing kernel vs standard published Black-Scholes values.

Reference case: S=100, K=100, T=1y, r=5%, sigma=20% (textbook values,
e.g. Hull, 'Options, Futures and Other Derivatives').
"""

from datetime import date, datetime

import pytest

from ceremyn.core.timeutils import IST
from ceremyn.data.services.chain_analytics import EXPIRY_CUTOFF
from ceremyn.data.services.pricing import (
    bs_greeks,
    bs_price,
    implied_vol,
    time_to_expiry_years,
)

S, K, T, R, SIGMA = 100.0, 100.0, 1.0, 0.05, 0.20


class TestPriceGoldenValues:
    def test_call_price(self) -> None:
        assert bs_price(S, K, T, R, SIGMA, is_call=True) == pytest.approx(10.4506, abs=1e-4)

    def test_put_price(self) -> None:
        assert bs_price(S, K, T, R, SIGMA, is_call=False) == pytest.approx(5.5735, abs=1e-4)

    def test_put_call_parity(self) -> None:
        import math

        call = bs_price(S, K, T, R, SIGMA, is_call=True)
        put = bs_price(S, K, T, R, SIGMA, is_call=False)
        assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-10)

    def test_expired_option_is_intrinsic(self) -> None:
        assert bs_price(105, 100, 0.0, R, SIGMA, is_call=True) == 5.0
        assert bs_price(105, 100, 0.0, R, SIGMA, is_call=False) == 0.0

    @pytest.mark.parametrize(
        ("strike", "now", "is_call"),
        [
            (23300.0, datetime(2025, 7, 29, 10, 30, tzinfo=IST), False),
            (24700.0, datetime(2025, 7, 29, 10, 30, tzinfo=IST), True),
            (24600.0, datetime(2025, 7, 29, 12, 0, tzinfo=IST), True),
            (23700.0, datetime(2025, 7, 29, 14, 30, tzinfo=IST), False),
        ],
    )
    def test_near_expiry_price_never_goes_negative(
        self, strike: float, now: datetime, is_call: bool
    ) -> None:
        expiry = date(2025, 7, 29)
        seconds_to_expiry = (
            datetime.combine(expiry, EXPIRY_CUTOFF, tzinfo=IST) - now
        ).total_seconds()
        price = bs_price(
            24000.0,
            strike,
            time_to_expiry_years(seconds_to_expiry),
            0.065,
            0.15,
            is_call,
        )
        assert 0.0 <= price < 1e-8

    def test_invalid_inputs_rejected(self) -> None:
        with pytest.raises(ValueError):
            bs_price(0, K, T, R, SIGMA, is_call=True)


class TestGreeksGoldenValues:
    def test_call_greeks(self) -> None:
        g = bs_greeks(S, K, T, R, SIGMA, is_call=True)
        assert g.delta == pytest.approx(0.636831, abs=1e-5)
        assert g.gamma == pytest.approx(0.018762, abs=1e-5)
        assert g.vega == pytest.approx(0.375240, abs=1e-5)  # per 1 vol point
        assert g.theta == pytest.approx(-6.41403 / 365, abs=1e-5)  # per calendar day
        assert g.rho == pytest.approx(0.532325, abs=1e-5)  # per 1% rate move

    def test_put_greeks(self) -> None:
        g = bs_greeks(S, K, T, R, SIGMA, is_call=False)
        assert g.delta == pytest.approx(-0.363169, abs=1e-5)
        assert g.gamma == pytest.approx(0.018762, abs=1e-5)  # same as call
        assert g.rho == pytest.approx(0.532325 - 0.951229, abs=1e-5)

    def test_deep_itm_call_delta_near_one(self) -> None:
        g = bs_greeks(150, 100, 0.05, R, SIGMA, is_call=True)
        assert g.delta > 0.999

    def test_expired_greeks_are_step_function(self) -> None:
        assert bs_greeks(105, 100, 0.0, R, SIGMA, is_call=True).delta == 1.0
        assert bs_greeks(95, 100, 0.0, R, SIGMA, is_call=False).delta == -1.0


class TestImpliedVol:
    @pytest.mark.parametrize("sigma", [0.05, 0.14, 0.35, 0.80])
    @pytest.mark.parametrize("is_call", [True, False])
    def test_round_trip(self, sigma: float, is_call: bool) -> None:
        price = bs_price(S, 105.0, 0.25, R, sigma, is_call)
        recovered = implied_vol(price, S, 105.0, 0.25, R, is_call)
        assert recovered == pytest.approx(sigma, abs=1e-6)

    def test_price_below_arbitrage_bound_returns_none(self) -> None:
        # A call can never be worth less than its discounted intrinsic value.
        assert implied_vol(0.01, 120.0, 100.0, 0.25, R, is_call=True) is None

    def test_zero_price_returns_none(self) -> None:
        assert implied_vol(0.0, S, K, T, R, is_call=True) is None

    def test_expired_returns_none(self) -> None:
        assert implied_vol(5.0, S, K, 0.0, R, is_call=True) is None


def test_time_to_expiry_act365() -> None:
    assert time_to_expiry_years(365 * 24 * 3600) == pytest.approx(1.0)
    assert time_to_expiry_years(-100.0) == 0.0

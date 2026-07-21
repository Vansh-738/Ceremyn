from datetime import date, datetime
from decimal import Decimal

import pytest

from ceremyn.core.timeutils import IST
from ceremyn.data.services.chain_analytics import (
    EXPIRY_CUTOFF,
    ChainAnalyticsService,
    expiry_moment,
    iv_percentile,
    iv_rank,
    max_pain,
)
from ceremyn.data.services.pricing import bs_price, time_to_expiry_years
from ceremyn.domain import ChainEntry, OptionChainSnapshot, OptionType, Quote
from tests.unit.domain.conftest import make_contract

R = 0.065
TS = datetime(2025, 7, 14, 10, 0, tzinfo=IST)
EXPIRY = date(2025, 7, 29)
SPOT = 24000.0


def priced_entry(strike: int, option_type: OptionType, sigma: float, oi: int = 0) -> ChainEntry:
    """Entry whose quote is the exact BS price at `sigma` (so IV must round-trip)."""
    contract = make_contract(strike=strike, option_type=option_type, expiry=EXPIRY)
    t = time_to_expiry_years(
        (datetime.combine(EXPIRY, EXPIRY_CUTOFF, tzinfo=IST) - TS).total_seconds()
    )
    price = Decimal(str(bs_price(SPOT, float(strike), t, R, sigma, option_type is OptionType.CALL)))
    quote = Quote(
        tradingsymbol=contract.tradingsymbol,
        timestamp=TS,
        last_price=price,
        bid=price,
        ask=price,
        open_interest=oi,
    )
    return ChainEntry(contract=contract, quote=quote)


def make_snapshot(entries: tuple[ChainEntry, ...]) -> OptionChainSnapshot:
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=EXPIRY,
        spot=Decimal(str(SPOT)),
        timestamp=TS,
        entries=entries,
    )


class TestEnrich:
    def test_iv_round_trips_through_enrichment(self) -> None:
        snapshot = make_snapshot(
            (
                priced_entry(24000, OptionType.CALL, sigma=0.15),
                priced_entry(24000, OptionType.PUT, sigma=0.17),
            )
        )
        enriched = ChainAnalyticsService(risk_free_rate=R).enrich(snapshot)
        call, put = enriched.entries
        assert call.greeks is not None and put.greeks is not None
        assert call.greeks.iv == pytest.approx(0.15, abs=1e-6)
        assert put.greeks.iv == pytest.approx(0.17, abs=1e-6)
        assert 0 < call.greeks.delta < 1
        assert -1 < put.greeks.delta < 0
        assert call.greeks.theta < 0

    def test_unpriceable_entry_left_untouched(self) -> None:
        contract = make_contract(strike=24000, expiry=EXPIRY)
        entry = ChainEntry(contract=contract, quote=None)
        enriched = ChainAnalyticsService(risk_free_rate=R).enrich(make_snapshot((entry,)))
        assert enriched.entries[0].greeks is None

    def test_atm_iv_averages_call_and_put(self) -> None:
        snapshot = make_snapshot(
            (
                priced_entry(24000, OptionType.CALL, sigma=0.15),
                priced_entry(24000, OptionType.PUT, sigma=0.17),
                priced_entry(24500, OptionType.CALL, sigma=0.30),  # not ATM
            )
        )
        service = ChainAnalyticsService(risk_free_rate=R)
        atm = service.atm_iv(service.enrich(snapshot))
        assert atm == pytest.approx(0.16, abs=1e-4)

    def test_expiry_moment_is_1530_ist_on_expiry_day(self) -> None:
        snapshot = make_snapshot((priced_entry(24000, OptionType.CALL, sigma=0.15),))
        moment = expiry_moment(snapshot)
        assert (moment.hour, moment.minute) == (15, 30)
        assert moment.tzinfo is not None


class TestIvHistoryStats:
    def test_iv_rank(self) -> None:
        assert iv_rank(25.0, [10.0, 30.0]) == pytest.approx(75.0)
        assert iv_rank(10.0, [10.0, 30.0]) == 0.0
        assert iv_rank(30.0, [10.0, 30.0]) == 100.0

    def test_iv_rank_clamped_and_degenerate(self) -> None:
        assert iv_rank(50.0, [10.0, 30.0]) == 100.0  # above historical max
        assert iv_rank(20.0, [15.0]) is None
        assert iv_rank(20.0, [15.0, 15.0]) is None

    def test_iv_percentile(self) -> None:
        history = [10.0, 20.0, 30.0, 40.0]
        assert iv_percentile(35.0, history) == pytest.approx(75.0)
        assert iv_percentile(5.0, history) == 0.0
        assert iv_percentile(45.0, history) == 100.0
        assert iv_percentile(1.0, []) is None


class TestMaxPain:
    def test_max_pain_minimizes_writer_payout(self) -> None:
        entries = (
            priced_entry(23000, OptionType.CALL, sigma=0.2, oi=100),
            priced_entry(23100, OptionType.CALL, sigma=0.2, oi=40),
            priced_entry(23100, OptionType.PUT, sigma=0.2, oi=60),
            priced_entry(23200, OptionType.PUT, sigma=0.2, oi=100),
        )
        # Payouts: settle@23000 -> 26_000; @23100 -> 20_000; @23200 -> 24_000.
        assert max_pain(make_snapshot(entries)) == Decimal(23100)

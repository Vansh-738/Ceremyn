from datetime import datetime
from decimal import Decimal

import pytest

from ceremyn.domain import (
    EquityInstrument,
    Exchange,
    KillSwitchState,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Position,
    Side,
    Signal,
    SignalAction,
)
from ceremyn.domain.signals import SignalLeg
from ceremyn.risk.context import RiskContext
from tests.unit.risk.conftest import make_contract, make_signal


def make_equity(symbol: str = "RELIANCE") -> EquityInstrument:
    return EquityInstrument(tradingsymbol=symbol, exchange=Exchange.NSE, underlying=symbol)


def make_equity_signal(
    *, created_at: datetime, legs: tuple[SignalLeg, ...], metadata: dict[str, object] | None = None
) -> Signal:
    """`make_signal` in conftest hardcodes a required option `expiry` -- an equity
    signal has none, so this is a separate, narrow helper rather than widening
    that shared one for every other (option-only) test in this file."""
    return Signal(
        strategy_id="strategy-1",
        created_at=created_at,
        market_timestamp=created_at,
        signal_type=SignalAction.ENTER,
        reason="test equity signal",
        metadata=metadata or {},
        legs=legs,
        underlying=legs[0].contract.underlying,
    )


def test_context_projects_positions_exposure_margin_and_greeks(
    base_settings,
    ist_now,
    portfolio,
    option_contract,
    second_contract,
) -> None:
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(
            SignalLeg(contract=second_contract, side=Side.SELL, lots=2),
            SignalLeg(
                contract=make_contract(
                    symbol="NIFTY26JUL25200CE",
                    strike="25200",
                    expiry=option_contract.expiry,
                ),
                side=Side.BUY,
                lots=1,
            ),
        ),
        metadata={
            "margin_required": "125000",
            "signal_greeks": {"delta": -75.0, "gamma": 4.0, "theta": -20.0, "vega": 60.0},
        },
    )

    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert context.signal_lots_total == 3
    assert context.projected_margin_used == Decimal("225000")
    assert context.projected_open_positions == 3
    assert context.projected_open_positions_in_underlying == 3
    assert context.projected_exposure.short_option_units == 75
    assert context.projected_exposure.net_option_units == -50
    assert context.projected_portfolio_greeks.delta == -125.0
    assert context.projected_portfolio_greeks.gamma == 6.0


def test_projected_margin_used_computes_from_legs_when_no_metadata_supplied(
    base_settings,
    ist_now,
    portfolio,
    option_contract,
    second_contract,
) -> None:
    """No strategy ever sets `margin_required`/`projected_margin_used` metadata in
    production — this is the path every real signal actually takes."""
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(
            SignalLeg(contract=second_contract, side=Side.SELL, lots=2),
            SignalLeg(
                contract=make_contract(
                    symbol="NIFTY26JUL25200CE",
                    strike="25200",
                    expiry=option_contract.expiry,
                ),
                side=Side.BUY,
                lots=1,
            ),
        ),
    )

    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    # Full net-projected-position recompute, not additive to portfolio.margin_used:
    # pre-existing option_contract short (25000 * 25 * 0.15 = 93750) + this signal's
    # net-short second_contract leg (25100 * 50 * 0.15 = 188250) + its net-long new
    # leg (25200 * 25 * 0.0 = 0).
    assert context.signal_margin_required == Decimal("282000")
    assert context.projected_margin_used == Decimal("282000")


def test_projected_margin_used_ignores_a_signal_that_only_closes_a_long(
    base_settings,
    ist_now,
    option_contract,
) -> None:
    """A SELL leg that closes an existing long must not be charged short-side margin
    just because the leg itself sells -- an exit signal reduces risk, it doesn't
    open new exposure. (Regression: this exact miscount blocked every real exit
    signal `long_strangle` ever emitted in a real-data backtest.)"""
    long_position = Position(contract=option_contract, quantity=25, avg_price=Decimal("110"))
    portfolio_snapshot = PortfolioSnapshot(
        positions=(long_position,),
        buying_power=Decimal("900000"),
        margin_used=Decimal("0"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        daily_pnl=Decimal("0"),
        portfolio_greeks=PortfolioGreeks(delta=50.0, gamma=2.0, theta=-20.0, vega=30.0),
        exposure=PortfolioExposure(
            gross_notional=Decimal("625000"),
            net_notional=Decimal("625000"),
            short_option_units=0,
            net_option_units=25,
            by_underlying={"NIFTY": Decimal("625000")},
        ),
        drawdown=Decimal("0"),
        kill_switch_state=KillSwitchState.DISARMED,
    )
    exit_signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
    )

    context = RiskContext.from_inputs(
        portfolio=portfolio_snapshot,
        signal=exit_signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert context.projected_position_quantities[option_contract.tradingsymbol] == 0
    assert context.signal_margin_required == Decimal("0")
    assert context.projected_margin_used == Decimal("0")


def test_context_uses_projected_metadata_overrides(
    base_settings,
    ist_now,
    portfolio,
    signal,
) -> None:
    overridden_signal = signal.model_copy(
        update={
            "metadata": {
                "projected_margin_used": "300000",
                "projected_portfolio_greeks": {
                    "delta": 10.0,
                    "gamma": 1.0,
                    "theta": -5.0,
                    "vega": 3.0,
                },
                "projected_exposure": {
                    "gross_notional": "1000000",
                    "net_notional": "100000",
                    "short_option_units": 10,
                    "net_option_units": 10,
                    "by_underlying": {"NIFTY": "100000"},
                },
            }
        }
    )

    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=overridden_signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert context.projected_margin_used == Decimal("300000")
    assert context.projected_portfolio_greeks == PortfolioGreeks(
        delta=10.0, gamma=1.0, theta=-5.0, vega=3.0, rho=0.0
    )
    assert context.projected_exposure == PortfolioExposure(
        gross_notional=Decimal("1000000"),
        net_notional=Decimal("100000"),
        short_option_units=10,
        net_option_units=10,
        by_underlying={"NIFTY": Decimal("100000")},
    )


def _empty_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        positions=(),
        buying_power=Decimal("100000"),
        margin_used=Decimal("0"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        daily_pnl=Decimal("0"),
        portfolio_greeks=PortfolioGreeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0),
        exposure=PortfolioExposure(gross_notional=Decimal("0"), net_notional=Decimal("0")),
        drawdown=Decimal("0"),
        kill_switch_state=KillSwitchState.DISARMED,
    )


class TestNonOptionReferencePrice:
    """Regression suite: before this fix, every non-option leg silently priced at
    Decimal("0") in signal_notional/signal_margin_required/projected_exposure --
    an equity trade was invisible to every notional/margin/concentration limit."""

    def test_equity_signal_notional_requires_reference_price(self, base_settings, ist_now) -> None:
        equity = make_equity()
        signal = make_equity_signal(
            created_at=ist_now,
            legs=(SignalLeg(contract=equity, side=Side.BUY, lots=10),),
        )
        context = RiskContext.from_inputs(
            portfolio=_empty_portfolio(),
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
        with pytest.raises(ValueError, match="reference_prices"):
            _ = context.signal_notional

    def test_equity_signal_notional_uses_supplied_reference_price(
        self, base_settings, ist_now
    ) -> None:
        equity = make_equity()
        signal = make_equity_signal(
            created_at=ist_now,
            legs=(SignalLeg(contract=equity, side=Side.BUY, lots=10),),
            metadata={"reference_prices": {"RELIANCE": "1489.25"}},
        )
        context = RiskContext.from_inputs(
            portfolio=_empty_portfolio(),
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
        assert context.signal_notional == Decimal("14892.50")

    def test_equity_margin_required_is_full_notional_not_an_option_ratio(
        self, base_settings, ist_now
    ) -> None:
        """Equity delivery (CNC) is paid for in full -- it must not be discounted by
        the option premium-based short/long margin ratios."""
        equity = make_equity()
        signal = make_equity_signal(
            created_at=ist_now,
            legs=(SignalLeg(contract=equity, side=Side.BUY, lots=10),),
            metadata={"reference_prices": {"RELIANCE": "1489.25"}},
        )
        context = RiskContext.from_inputs(
            portfolio=_empty_portfolio(),
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
        assert context.signal_margin_required == Decimal("14892.50")

    def test_equity_projected_exposure_uses_supplied_reference_price(
        self, base_settings, ist_now
    ) -> None:
        equity = make_equity()
        signal = make_equity_signal(
            created_at=ist_now,
            legs=(SignalLeg(contract=equity, side=Side.BUY, lots=10),),
            metadata={"reference_prices": {"RELIANCE": "1489.25"}},
        )
        context = RiskContext.from_inputs(
            portfolio=_empty_portfolio(),
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
        assert context.projected_exposure.gross_notional == Decimal("14892.50")
        assert context.projected_exposure.net_notional == Decimal("14892.50")

    def test_existing_equity_position_not_touched_by_signal_uses_avg_price(
        self, base_settings, ist_now
    ) -> None:
        """A pre-existing equity position this signal doesn't reference must not
        force this unrelated signal's metadata to price it -- it falls back to its
        own recorded avg_price instead."""
        held = make_equity(symbol="TCS")
        existing_position = Position(contract=held, quantity=5, avg_price=Decimal("3500"))
        portfolio_snapshot = PortfolioSnapshot(
            positions=(existing_position,),
            buying_power=Decimal("100000"),
            margin_used=Decimal("17500"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            daily_pnl=Decimal("0"),
            portfolio_greeks=PortfolioGreeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0),
            exposure=PortfolioExposure(
                gross_notional=Decimal("17500"), net_notional=Decimal("17500")
            ),
            drawdown=Decimal("0"),
            kill_switch_state=KillSwitchState.DISARMED,
        )
        new_equity = make_equity(symbol="RELIANCE")
        signal = make_equity_signal(
            created_at=ist_now,
            legs=(SignalLeg(contract=new_equity, side=Side.BUY, lots=10),),
            metadata={"reference_prices": {"RELIANCE": "1489.25"}},
        )
        context = RiskContext.from_inputs(
            portfolio=portfolio_snapshot,
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
        # TCS (existing, untouched): 5 * 3500 = 17500 via avg_price fallback.
        # RELIANCE (this signal): 10 * 1489.25 = 14892.50 via metadata.
        assert context.signal_margin_required == Decimal("32392.50")

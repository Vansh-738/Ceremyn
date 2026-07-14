from decimal import Decimal

from alphaquant.domain import PortfolioExposure, PortfolioGreeks
from alphaquant.domain.enums import Side
from alphaquant.domain.signals import SignalLeg
from alphaquant.risk.context import RiskContext
from tests.unit.risk.conftest import make_contract, make_signal


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

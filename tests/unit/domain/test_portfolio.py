from decimal import Decimal

from alphaquant.domain import (
    KillSwitchState,
    OptionType,
    Order,
    OrderType,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Position,
    Side,
)
from tests.unit.domain.conftest import make_contract


def test_portfolio_snapshot_holds_strategy_and_risk_inputs() -> None:
    contract = make_contract(strike=24500, option_type=OptionType.CALL)
    position = Position(contract=contract, quantity=-75, avg_price=Decimal("150"))
    pending_order = Order(
        contract=contract,
        side=Side.BUY,
        quantity=75,
        order_type=OrderType.MARKET,
    )
    snapshot = PortfolioSnapshot(
        positions=(position,),
        pending_orders=(pending_order,),
        buying_power=Decimal("250000"),
        margin_used=Decimal("100000"),
        realized_pnl=Decimal("1200"),
        unrealized_pnl=Decimal("-350"),
        daily_pnl=Decimal("850"),
        portfolio_greeks=PortfolioGreeks(delta=-0.25, theta=125.0),
        exposure=PortfolioExposure(
            gross_notional=Decimal("500000"),
            net_notional=Decimal("-250000"),
            short_option_units=75,
            net_option_units=-75,
            by_underlying={"NIFTY": Decimal("-250000")},
        ),
        drawdown=Decimal("2500"),
        kill_switch_state=KillSwitchState.ARMED,
    )

    assert snapshot.positions == (position,)
    assert snapshot.pending_orders == (pending_order,)
    assert snapshot.portfolio_greeks.theta == 125.0
    assert snapshot.exposure.by_underlying["NIFTY"] == Decimal("-250000")
    assert snapshot.kill_switch_state is KillSwitchState.ARMED


def test_portfolio_snapshot_defaults_are_safe() -> None:
    snapshot = PortfolioSnapshot()

    assert snapshot.positions == ()
    assert snapshot.pending_orders == ()
    assert snapshot.buying_power == Decimal("0")
    assert snapshot.margin_used == Decimal("0")
    assert snapshot.kill_switch_state is KillSwitchState.DISARMED

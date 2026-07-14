from decimal import Decimal

from alphaquant.backtest.commission import CostBreakdown
from alphaquant.backtest.fills import VirtualFill
from alphaquant.domain import Fill, Order, Side
from alphaquant.domain.enums import OrderStatus, OrderType
from alphaquant.paper.portfolio import PaperPortfolio
from alphaquant.paper.reconciliation import Reconciler
from tests.unit.backtest.helpers import make_contract
from tests.unit.paper.conftest import TICK_ZERO


def virtual_fill(side: Side, quantity: int, price: str) -> VirtualFill:
    order = Order(
        contract=make_contract(),
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created_at=TICK_ZERO,
    )
    return VirtualFill(
        order=order,
        fill=Fill(order_id=order.id, quantity=quantity, price=Decimal(price), timestamp=TICK_ZERO),
        updated_order=order,
        cost_breakdown=CostBreakdown(),
        strategy_id="s",
    )


def apply(portfolio: PaperPortfolio, vf: VirtualFill) -> None:
    portfolio.apply_fill(
        fill=vf.fill,
        order=vf.updated_order,
        strategy_id=vf.strategy_id,
        signal_id=None,
        costs=vf.cost_breakdown.total,
    )


def test_reconciles_clean_when_matching() -> None:
    portfolio = PaperPortfolio()
    reconciler = Reconciler()
    vf = virtual_fill(Side.BUY, 25, "100")
    apply(portfolio, vf)
    reconciler.record_fill(vf)
    report = reconciler.reconcile(portfolio)
    assert report.reconciled is True
    assert report.drift == {}


def test_detects_drift_when_fill_not_applied() -> None:
    portfolio = PaperPortfolio()
    reconciler = Reconciler()
    vf = virtual_fill(Side.BUY, 25, "100")
    reconciler.record_fill(vf)  # recorded but NOT applied to the portfolio
    report = reconciler.reconcile(portfolio)
    assert report.reconciled is False
    assert report.drift[vf.order.contract.tradingsymbol] == -25
    assert report.drift_symbols == (vf.order.contract.tradingsymbol,)


def test_sell_reduces_expected_quantity() -> None:
    # Quantities must be whole lots (lot size 25): buy 2 lots, sell 1 -> net 25.
    portfolio = PaperPortfolio()
    reconciler = Reconciler()
    buy = virtual_fill(Side.BUY, 50, "100")
    sell = virtual_fill(Side.SELL, 25, "110")
    for vf in (buy, sell):
        apply(portfolio, vf)
        reconciler.record_fill(vf)
    report = reconciler.reconcile(portfolio)
    assert report.reconciled is True


def test_empty_session_reconciles() -> None:
    assert Reconciler().reconcile(PaperPortfolio()).reconciled is True

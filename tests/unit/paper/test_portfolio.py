from decimal import Decimal

from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.domain import Fill, Order, Side
from ceremyn.domain.enums import OrderStatus, OrderType
from ceremyn.paper.portfolio import PaperPortfolio
from tests.unit.backtest.helpers import make_contract
from tests.unit.paper.conftest import TICK_ZERO


def buy_order() -> Order:
    return Order(
        contract=make_contract(),
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created_at=TICK_ZERO,
    )


def test_apply_fill_delegates_accounting() -> None:
    portfolio = PaperPortfolio(PortfolioConfig(initial_cash=Decimal("1000000")))
    order = buy_order()
    portfolio.apply_fill(
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("100"), timestamp=TICK_ZERO),
        order=order,
        strategy_id="s",
        signal_id=None,
        costs=Decimal("10"),
    )
    # Cash reduced by 25*100 + 10 costs.
    assert portfolio.cash == Decimal("1000000") - Decimal("2500") - Decimal("10")
    assert portfolio.positions[order.contract.tradingsymbol].quantity == 25


def test_mark_returns_snapshot_with_pnl() -> None:
    portfolio = PaperPortfolio(PortfolioConfig(initial_cash=Decimal("1000000")))
    order = buy_order()
    portfolio.apply_fill(
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("100"), timestamp=TICK_ZERO),
        order=order,
        strategy_id="s",
        signal_id=None,
        costs=Decimal("0"),
    )
    snapshot = portfolio.mark(
        timestamp=TICK_ZERO,
        last_prices={order.contract.tradingsymbol: Decimal("110")},
    )
    assert snapshot.unrealized_pnl == Decimal("250")  # (110-100)*25
    assert len(portfolio.equity_curve) == 1


def test_session_statistics_uses_shared_metrics() -> None:
    portfolio = PaperPortfolio(PortfolioConfig(initial_cash=Decimal("1000000")))
    portfolio.mark(timestamp=TICK_ZERO, last_prices={})
    stats = portfolio.session_statistics()
    assert stats.total_return == 0.0  # no trades yet


def test_closed_trades_exposed() -> None:
    portfolio = PaperPortfolio()
    assert portfolio.closed_trades == ()


def test_snapshot_returns_latest_mark() -> None:
    portfolio = PaperPortfolio(PortfolioConfig(initial_cash=Decimal("500000")))
    portfolio.mark(timestamp=TICK_ZERO, last_prices={})
    snapshot = portfolio.snapshot()
    assert snapshot.buying_power == Decimal("500000")

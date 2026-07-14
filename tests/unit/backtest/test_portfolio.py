from datetime import datetime
from decimal import Decimal

from alphaquant.backtest.portfolio import BacktestPortfolio, PortfolioConfig
from alphaquant.domain import Fill, Order
from alphaquant.domain.enums import OrderType, Side
from tests.unit.backtest.helpers import make_chain, make_contract


def test_portfolio_tracks_cash_positions_and_closed_trades(
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
    contract = make_contract()
    portfolio = BacktestPortfolio(PortfolioConfig(initial_cash=Decimal("100000")))
    buy_order = Order(
        contract=contract,
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        created_at=timestamp_one,
    )
    sell_order = Order(
        contract=contract,
        side=Side.SELL,
        quantity=25,
        order_type=OrderType.MARKET,
        created_at=timestamp_two,
    )

    portfolio.apply_fill(
        fill=Fill(
            order_id=buy_order.id,
            quantity=25,
            price=Decimal("100"),
            timestamp=timestamp_one,
        ),
        order=buy_order,
        strategy_id="strategy-a",
        signal_id=None,
        costs=Decimal("10"),
    )
    portfolio.apply_fill(
        fill=Fill(
            order_id=sell_order.id,
            quantity=25,
            price=Decimal("110"),
            timestamp=timestamp_two,
        ),
        order=sell_order,
        strategy_id="strategy-a",
        signal_id=None,
        costs=Decimal("10"),
    )
    snapshot = portfolio.mark_to_market(
        timestamp=timestamp_two,
        last_prices={contract.tradingsymbol: Decimal("110")},
    )

    assert snapshot.realized_pnl == Decimal("250")
    assert len(portfolio.closed_trades) == 1
    assert portfolio.closed_trades[0].net_pnl == Decimal("230")
    assert portfolio.cash == Decimal("100230")


def test_portfolio_marks_margin_and_equity(timestamp_one: datetime) -> None:
    contract = make_contract()
    chain = make_chain(
        timestamp=timestamp_one,
        last_price="100",
        bid="99",
        ask="101",
        contract=contract,
    )
    portfolio = BacktestPortfolio(PortfolioConfig(initial_cash=Decimal("100000")))
    order = Order(
        contract=contract,
        side=Side.SELL,
        quantity=25,
        order_type=OrderType.MARKET,
        created_at=timestamp_one,
    )
    portfolio.apply_fill(
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("99"), timestamp=timestamp_one),
        order=order,
        strategy_id="strategy-a",
        signal_id=None,
        costs=Decimal("0"),
    )
    snapshot = portfolio.mark_to_market(
        timestamp=timestamp_one,
        last_prices={chain.entries[0].contract.tradingsymbol: Decimal("100")},
    )

    assert snapshot.margin_used > Decimal("0")
    assert snapshot.buying_power < snapshot.margin_used + portfolio.cash

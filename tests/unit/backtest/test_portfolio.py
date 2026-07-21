from datetime import UTC, datetime
from decimal import Decimal

from ceremyn.backtest.portfolio import BacktestPortfolio, PortfolioConfig
from ceremyn.domain import Fill, Order
from ceremyn.domain.enums import KillSwitchState, OrderType, Side
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


def test_daily_pnl_resets_at_the_start_of_each_trading_day() -> None:
    """`daily_pnl` must reflect today's move, not cumulative loss since inception --
    otherwise `MaximumDailyLossRule` permanently blocks new entries after one bad day
    (regression: this exact bug silently blocked a month of `long_strangle` re-entries
    in a real-data backtest after its first losing trade)."""
    contract = make_contract()
    portfolio = BacktestPortfolio(PortfolioConfig(initial_cash=Decimal("100000")))
    day_one = datetime(2026, 7, 14, 4, 20, tzinfo=UTC)
    day_two = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)

    buy_order = Order(
        contract=contract,
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        created_at=day_one,
    )
    portfolio.apply_fill(
        fill=Fill(order_id=buy_order.id, quantity=25, price=Decimal("100"), timestamp=day_one),
        order=buy_order,
        strategy_id="strategy-a",
        signal_id=None,
        costs=Decimal("0"),
    )

    day_one_snapshot = portfolio.mark_to_market(
        timestamp=day_one, last_prices={contract.tradingsymbol: Decimal("80")}
    )
    assert day_one_snapshot.daily_pnl == Decimal("-500")  # (80 - 100) * 25

    # Next trading day, no new fills, price unchanged: still down overall, but
    # `daily_pnl` resets relative to today's own opening equity.
    day_two_snapshot = portfolio.mark_to_market(
        timestamp=day_two, last_prices={contract.tradingsymbol: Decimal("80")}
    )
    assert day_two_snapshot.daily_pnl == Decimal("0")
    assert day_two_snapshot.unrealized_pnl == Decimal("-500")


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


def test_portfolio_triggers_kill_switch_on_drawdown(timestamp_one: datetime) -> None:
    contract = make_contract()
    portfolio = BacktestPortfolio(
        PortfolioConfig(
            initial_cash=Decimal("100000"),
            kill_switch_drawdown_limit=Decimal("100"),
        )
    )
    order = Order(
        contract=contract,
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        created_at=timestamp_one,
    )
    portfolio.apply_fill(
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("100"), timestamp=timestamp_one),
        order=order,
        strategy_id="strategy-a",
        signal_id=None,
        costs=Decimal("0"),
    )

    snapshot = portfolio.mark_to_market(
        timestamp=timestamp_one,
        last_prices={contract.tradingsymbol: Decimal("95")},
    )

    # True drawdown is the real loss (100 - 95) * 25 = 125, not cash + unrealized_pnl's
    # double-counted 2625 (the bug `mark_to_market`'s market-value fix corrects).
    assert snapshot.drawdown == Decimal("125")
    assert snapshot.kill_switch_state is KillSwitchState.TRIGGERED

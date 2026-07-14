"""Performance metric calculations."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from math import sqrt
from typing import Any

import numpy as np

from alphaquant.backtest.ledger import ClosedTrade
from alphaquant.backtest.statistics import BacktestStatistics, EquityPoint, ReturnBucket


def _to_float(value: Decimal) -> float:
    return float(value)


def compute_statistics(
    *,
    equity_curve: tuple[EquityPoint, ...],
    closed_trades: tuple[ClosedTrade, ...],
    initial_cash: Decimal,
) -> BacktestStatistics:
    if not equity_curve:
        return BacktestStatistics()

    equities = np.array([_to_float(point.equity) for point in equity_curve], dtype=float)
    returns = (
        np.diff(equities) / equities[:-1]
        if len(equities) > 1
        else np.array([], dtype=float)
    )
    total_return = (
        ((equities[-1] / _to_float(initial_cash)) - 1.0) * 100.0
        if initial_cash > 0
        else 0.0
    )
    duration_days = max((equity_curve[-1].timestamp - equity_curve[0].timestamp).days, 1)
    cagr = (
        ((equities[-1] / _to_float(initial_cash)) ** (365.0 / duration_days) - 1.0) * 100.0
        if initial_cash > 0
        else 0.0
    )
    downside = returns[returns < 0]
    sharpe = _annualized_ratio(returns)
    sortino = _annualized_ratio(returns, downside if downside.size else None)
    max_drawdown = max((float(point.drawdown) for point in equity_curve), default=0.0)
    calmar = (cagr / max_drawdown * 100.0) if max_drawdown > 0 else 0.0

    winners = [trade for trade in closed_trades if trade.net_pnl > 0]
    losers = [trade for trade in closed_trades if trade.net_pnl < 0]
    gross_profit = sum((trade.net_pnl for trade in winners), Decimal("0"))
    gross_loss = abs(sum((trade.net_pnl for trade in losers), Decimal("0")))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else float(gross_profit > 0)
    trade_count = len(closed_trades)
    expectancy = (
        float(sum((trade.net_pnl for trade in closed_trades), Decimal("0")) / trade_count)
        if trade_count
        else 0.0
    )
    average_win = (
        float(sum((trade.net_pnl for trade in winners), Decimal("0")) / len(winners))
        if winners
        else 0.0
    )
    average_loss = (
        float(sum((trade.net_pnl for trade in losers), Decimal("0")) / len(losers))
        if losers
        else 0.0
    )
    largest_win = float(max((trade.net_pnl for trade in winners), default=Decimal("0")))
    largest_loss = float(min((trade.net_pnl for trade in losers), default=Decimal("0")))
    win_rate = (len(winners) / trade_count * 100.0) if trade_count else 0.0
    loss_rate = (len(losers) / trade_count * 100.0) if trade_count else 0.0
    avg_holding = _average_holding_hours(closed_trades)
    monthly_returns = _bucket_returns(equity_curve, "%Y-%m")
    yearly_returns = _bucket_returns(equity_curve, "%Y")

    return BacktestStatistics(
        total_return=round(total_return, 4),
        cagr=round(cagr, 4),
        sharpe=round(sharpe, 4),
        sortino=round(sortino, 4),
        calmar=round(calmar, 4),
        profit_factor=round(profit_factor, 4),
        expectancy=round(expectancy, 4),
        maximum_drawdown=round(max_drawdown, 4),
        average_win=round(average_win, 4),
        average_loss=round(average_loss, 4),
        largest_win=round(largest_win, 4),
        largest_loss=round(largest_loss, 4),
        win_rate=round(win_rate, 4),
        loss_rate=round(loss_rate, 4),
        average_holding_time_hours=round(avg_holding, 4),
        monthly_returns=monthly_returns,
        yearly_returns=yearly_returns,
    )


def _annualized_ratio(
    returns: np.ndarray[Any, Any],
    downside: np.ndarray[Any, Any] | None = None,
) -> float:
    if returns.size == 0:
        return 0.0
    denominator = (downside if downside is not None else returns).std(ddof=0)
    if denominator == 0:
        return 0.0
    return float(returns.mean() / denominator * sqrt(252))


def _average_holding_hours(closed_trades: tuple[ClosedTrade, ...]) -> float:
    if not closed_trades:
        return 0.0
    total = sum((trade.holding_time for trade in closed_trades), timedelta())
    return total.total_seconds() / 3600 / len(closed_trades)


def _bucket_returns(equity_curve: tuple[EquityPoint, ...], fmt: str) -> tuple[ReturnBucket, ...]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for point in equity_curve:
        buckets[point.timestamp.strftime(fmt)].append(float(point.equity))
    results = []
    for period, values in sorted(buckets.items()):
        if not values:
            continue
        start = values[0]
        end = values[-1]
        return_pct = ((end / start) - 1.0) * 100.0 if start else 0.0
        results.append(ReturnBucket(period=period, return_pct=round(return_pct, 4)))
    return tuple(results)

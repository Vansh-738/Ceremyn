"""Backtest report model."""

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.backtest.ledger import ClosedTrade
from alphaquant.backtest.statistics import BacktestStatistics, EquityPoint, ReturnBucket
from alphaquant.domain import PortfolioSnapshot, StrategyDefinition


class BacktestReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: StrategyDefinition
    statistics: BacktestStatistics
    final_portfolio: PortfolioSnapshot
    trade_ledger: tuple[ClosedTrade, ...] = ()
    equity_curve: tuple[EquityPoint, ...] = ()
    drawdown_curve: tuple[EquityPoint, ...] = ()
    monthly_returns: tuple[ReturnBucket, ...] = ()
    yearly_returns: tuple[ReturnBucket, ...] = ()
    strategy_summary: dict[str, str | float | int] = Field(default_factory=dict)
    performance_report: str = ""

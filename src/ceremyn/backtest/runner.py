"""Backtest runner."""

from collections.abc import Iterable
from typing import Any

from ceremyn.backtest.engine import BacktestConfig, BacktestEngine
from ceremyn.backtest.events import BacktestEvent
from ceremyn.backtest.metrics import compute_statistics
from ceremyn.backtest.report import BacktestReport
from ceremyn.domain import StrategyDefinition
from ceremyn.risk import RiskEngine
from ceremyn.strategies import Strategy


class BacktestRunner:
    def __init__(
        self,
        *,
        strategy: Strategy[Any],
        definition: StrategyDefinition,
        risk_engine: RiskEngine,
        config: BacktestConfig | None = None,
    ) -> None:
        self.engine = BacktestEngine(
            strategy=strategy,
            definition=definition,
            risk_engine=risk_engine,
            config=config,
        )
        self.definition = definition

    def run(self, events: Iterable[BacktestEvent]) -> BacktestReport:
        for event in sorted(events, key=lambda item: item.timestamp):
            self.engine.process_event(event)
        statistics = compute_statistics(
            equity_curve=tuple(self.engine.portfolio.equity_curve),
            closed_trades=self.engine.portfolio.closed_trades,
            initial_cash=self.engine.portfolio.config.initial_cash,
        )
        return BacktestReport(
            strategy=self.definition,
            statistics=statistics,
            final_portfolio=self.engine.final_snapshot(),
            trade_ledger=self.engine.portfolio.closed_trades,
            equity_curve=tuple(self.engine.portfolio.equity_curve),
            drawdown_curve=tuple(self.engine.portfolio.equity_curve),
            monthly_returns=statistics.monthly_returns,
            yearly_returns=statistics.yearly_returns,
            strategy_summary={
                "strategy_id": self.definition.id,
                "trade_count": len(self.engine.portfolio.closed_trades),
                "risk_decisions": len(self.engine.risk_decisions),
            },
            performance_report=(
                f"{self.definition.name}: total return {statistics.total_return:.2f}%, "
                f"sharpe {statistics.sharpe:.2f}, max drawdown {statistics.maximum_drawdown:.2f}"
            ),
        )

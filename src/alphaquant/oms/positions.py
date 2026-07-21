"""OMS portfolio wrapper over shared backtest accounting."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from alphaquant.backtest.ledger import ClosedTrade
from alphaquant.backtest.metrics import compute_statistics
from alphaquant.backtest.portfolio import BacktestPortfolio, PortfolioConfig
from alphaquant.backtest.statistics import BacktestStatistics, EquityPoint
from alphaquant.domain import Fill, Order, PortfolioSnapshot, Position


class OMSPortfolio:
    def __init__(self, config: PortfolioConfig | None = None) -> None:
        self._portfolio = BacktestPortfolio(config)

    @property
    def cash(self) -> Decimal:
        return self._portfolio.cash

    @property
    def positions(self) -> dict[str, Position]:
        return self._portfolio.positions

    @property
    def closed_trades(self) -> tuple[ClosedTrade, ...]:
        return self._portfolio.closed_trades

    @property
    def equity_curve(self) -> tuple[EquityPoint, ...]:
        """Every `mark()` call's (timestamp, cash, equity, drawdown), oldest first --
        real history, not a client-side reconstruction."""
        return tuple(self._portfolio.equity_curve)

    def apply_fill(
        self,
        *,
        fill: Fill,
        order: Order,
        strategy_id: str,
        signal_id: UUID | None,
        costs: Decimal,
    ) -> None:
        self._portfolio.apply_fill(
            fill=fill,
            order=order,
            strategy_id=strategy_id,
            signal_id=signal_id,
            costs=costs,
        )

    def mark(
        self,
        *,
        timestamp: datetime,
        last_prices: dict[str, Decimal],
        pending_orders: tuple[Order, ...] = (),
    ) -> PortfolioSnapshot:
        return self._portfolio.mark_to_market(
            timestamp=timestamp,
            last_prices=last_prices,
            pending_orders=pending_orders,
        )

    def snapshot(self) -> PortfolioSnapshot:
        return self._portfolio.snapshot()

    def session_statistics(self) -> BacktestStatistics:
        return compute_statistics(
            equity_curve=tuple(self._portfolio.equity_curve),
            closed_trades=self.closed_trades,
            initial_cash=self._portfolio.config.initial_cash,
        )

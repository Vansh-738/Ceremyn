"""Event-driven backtest engine."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.events import (
    BacktestEvent,
    CandleEvent,
    MarketSignalEvent,
    OptionChainEvent,
    QuoteEvent,
)
from ceremyn.backtest.fills import ExecutionContext, PendingOrderState
from ceremyn.backtest.portfolio import BacktestPortfolio, PortfolioConfig
from ceremyn.backtest.simulator import ExecutionSimulator, SimulationConfig
from ceremyn.data.services.chain_analytics import atm_iv, iv_rank
from ceremyn.domain import (
    Candle,
    OptionChainSnapshot,
    Order,
    PortfolioSnapshot,
    Quote,
    StrategyDefinition,
)
from ceremyn.risk import RiskDecision, RiskEngine
from ceremyn.strategies import Strategy, StrategyContext


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)


class BacktestEngine:
    def __init__(
        self,
        *,
        strategy: Strategy[Any],
        definition: StrategyDefinition,
        risk_engine: RiskEngine,
        config: BacktestConfig | None = None,
        portfolio: BacktestPortfolio | None = None,
        simulator: ExecutionSimulator | None = None,
    ) -> None:
        self.strategy = strategy
        self.definition = definition
        self.risk_engine = risk_engine
        self.config = config or BacktestConfig()
        self.portfolio = portfolio or BacktestPortfolio(self.config.portfolio)
        self.simulator = simulator or ExecutionSimulator(config=self.config.simulation)
        self.latest_chain: OptionChainSnapshot | None = None
        # Every chain event ever seen, keyed by expiry — lets a strategy that needs a second
        # expiry's chain at the same instant (e.g. a calendar spread) see it via
        # StrategyContext.other_expiries. `latest_chain` above still tracks the single
        # most-recently-arrived one, unchanged, for the existing single-expiry code paths.
        self.latest_chains: dict[date, OptionChainSnapshot] = {}
        self.quotes: dict[str, Quote] = {}
        self.candles: dict[str, Candle] = {}
        self.pending_orders: dict[str, list[PendingOrderState]] = defaultdict(list)
        self.risk_decisions: list[RiskDecision] = []
        # Real IV-rank history, accumulated per underlying exactly like
        # `RestPricePoller._iv_history` -- never fabricated, so strategies that need
        # it (short_strangle, iron_condor, short_straddle, ...) correctly stay
        # inactive until there's enough of it to be meaningful. Without this,
        # `StrategyContext.iv_rank` was always None in every backtest, so any
        # IV-rank-gated strategy could never be backtested at all -- a real parity
        # gap with the live/paper runners, not just a scripting limitation.
        self._iv_history: dict[str, list[float]] = defaultdict(list)

    def process_event(self, event: BacktestEvent) -> None:
        if isinstance(event, QuoteEvent):
            self.quotes[event.quote.tradingsymbol] = event.quote
        elif isinstance(event, CandleEvent):
            self.candles[event.candle.tradingsymbol] = event.candle
        elif isinstance(event, OptionChainEvent):
            self.latest_chain = event.chain
            self.latest_chains[event.chain.expiry] = event.chain
            for entry in event.chain.entries:
                if entry.quote is not None:
                    self.quotes[entry.contract.tradingsymbol] = entry.quote
        elif isinstance(event, MarketSignalEvent):
            return

        context = self._execution_context(event.timestamp)
        self._advance_pending_orders(context=context)
        if isinstance(event, OptionChainEvent):
            self._run_strategy(chain=event.chain)
        self.portfolio.mark_to_market(
            timestamp=event.timestamp,
            last_prices=self._last_prices(),
            pending_orders=self._pending_order_view(),
        )

    def final_snapshot(self) -> PortfolioSnapshot:
        return self.portfolio.snapshot()

    def _run_strategy(self, *, chain: OptionChainSnapshot) -> None:
        other_expiries = {
            expiry: c for expiry, c in self.latest_chains.items() if expiry != chain.expiry
        }
        rank = self._update_iv_history(chain)
        strategy_context = StrategyContext(
            chain=chain,
            portfolio=self.portfolio.snapshot(),
            now=chain.timestamp,
            other_expiries=other_expiries,
            iv_rank=rank,
        )
        for signal in self.strategy.on_chain(strategy_context):
            decision = self.risk_engine.evaluate(
                self.portfolio.snapshot(),
                signal,
                evaluated_at=chain.timestamp,
            )
            self.risk_decisions.append(decision)
            if not decision.approved:
                continue
            orders = self.simulator.orders_from_signal(signal, created_at=chain.timestamp)
            for order in orders:
                self.pending_orders[signal.strategy_id].append(
                    PendingOrderState(order=order, remaining_quantity=order.quantity)
                )
            self._advance_pending_orders(context=self._execution_context(chain.timestamp))

    _IV_HISTORY_MAXLEN = 1000

    def _update_iv_history(self, chain: OptionChainSnapshot) -> float | None:
        """Mirrors `RestPricePoller`'s own IV-rank bookkeeping so backtests gate on
        IV rank exactly like live/paper, instead of always seeing `iv_rank=None`."""
        current_iv = atm_iv(chain)
        if current_iv is None:
            return None
        history = self._iv_history[chain.underlying]
        rank = iv_rank(current_iv, history)
        history.append(current_iv)
        del history[: -self._IV_HISTORY_MAXLEN]
        return rank

    def _advance_pending_orders(self, *, context: ExecutionContext) -> None:
        if not self.pending_orders:
            return
        next_pending: dict[str, list[PendingOrderState]] = defaultdict(list)
        for strategy_id, states in self.pending_orders.items():
            pending, fills = self.simulator.simulate_pending(
                tuple(states),
                context=context,
                strategy_id=strategy_id,
            )
            next_pending[strategy_id].extend(pending)
            for virtual_fill in fills:
                self.portfolio.apply_fill(
                    fill=virtual_fill.fill,
                    order=virtual_fill.order,
                    strategy_id=virtual_fill.strategy_id,
                    signal_id=virtual_fill.signal_id,
                    costs=virtual_fill.cost_breakdown.total,
                )
        self.pending_orders = next_pending

    def _execution_context(self, timestamp: datetime) -> ExecutionContext:
        return ExecutionContext(
            timestamp=timestamp,
            chain=self.latest_chain,
            quotes=dict(self.quotes),
            candles=dict(self.candles),
        )

    def _last_prices(self) -> dict[str, Decimal]:
        prices: dict[str, Decimal] = {}
        if self.latest_chain is not None:
            for entry in self.latest_chain.entries:
                if entry.quote is not None:
                    prices[entry.contract.tradingsymbol] = entry.quote.last_price
        for symbol, quote in self.quotes.items():
            prices[symbol] = quote.last_price
        return prices

    def _pending_order_view(self) -> tuple[Order, ...]:
        return tuple(state.order for states in self.pending_orders.values() for state in states)

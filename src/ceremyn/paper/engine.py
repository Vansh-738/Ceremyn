"""PaperTradingEngine: the real-time orchestrator.

Each `on_tick` runs the same pipeline as the backtester — features, strategy, risk,
order construction, execution, portfolio marking — but over a live tick, with the paper
broker's order queue and latency in between. Everything is composed from existing
components; the engine only sequences them and feeds the monitor, journal, and reconciler.

Fills are always simulated locally: no broker order API, no live orders.
"""

import time
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.fills import ExecutionContext
from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.domain import OptionChainSnapshot, PortfolioSnapshot, Signal
from ceremyn.features.context import FeatureContext
from ceremyn.features.engine import FeatureEngine
from ceremyn.features.models import FeatureSet
from ceremyn.paper.broker import PaperBroker, PaperBrokerConfig
from ceremyn.paper.events import (
    MarketTick,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
    RiskEvaluated,
    SignalGenerated,
)
from ceremyn.paper.fills import apply_virtual_fill, fill_event
from ceremyn.paper.journal import PaperJournal
from ceremyn.paper.monitor import PaperMonitor
from ceremyn.paper.orders import PaperOMS
from ceremyn.paper.portfolio import PaperPortfolio
from ceremyn.paper.reconciliation import Reconciler, ReconciliationReport
from ceremyn.risk import RiskEngine
from ceremyn.strategies import Strategy, StrategyContext


class MarketDataFeed(Protocol):
    """A source of market ticks. Production wraps ChainService; tests inject a list."""

    def stream(self) -> Iterable[MarketTick]: ...


class PaperEngineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    broker: PaperBrokerConfig = Field(default_factory=PaperBrokerConfig)
    compute_features: bool = True
    reconcile_each_tick: bool = True


class TickResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    signals: int = 0
    fills: tuple[OrderFilled, ...] = ()
    rejections: tuple[OrderRejected, ...] = ()
    snapshot: PortfolioSnapshot
    features: FeatureSet | None = None
    reconciliation: ReconciliationReport | None = None


class PaperTradingEngine:
    def __init__(
        self,
        *,
        strategies: list[Strategy[Any]],
        risk_engine: RiskEngine,
        config: PaperEngineConfig | None = None,
        journal: PaperJournal | None = None,
        monitor: PaperMonitor | None = None,
        feature_engine: FeatureEngine | None = None,
    ) -> None:
        self.config = config or PaperEngineConfig()
        self.strategies = strategies
        self.risk_engine = risk_engine
        self.portfolio = PaperPortfolio(self.config.portfolio)
        self.broker = PaperBroker(self.config.broker)
        self.oms = PaperOMS(self.broker)
        self.journal = journal if journal is not None else PaperJournal("paper-session")
        self.monitor = monitor if monitor is not None else PaperMonitor()
        self.reconciler = Reconciler()
        self.feature_engine = feature_engine
        self.latest_features: FeatureSet | None = None

    def run(self, feed: MarketDataFeed) -> list[TickResult]:
        return [self.on_tick(tick) for tick in feed.stream()]

    def on_tick(self, tick: MarketTick) -> TickResult:
        as_of = tick.as_of
        context = ExecutionContext(timestamp=as_of, chain=tick.chain)

        fills = self._settle_pending(context, as_of=as_of)
        snapshot = self.portfolio.mark(
            timestamp=as_of,
            last_prices=_last_prices(tick.chain),
            pending_orders=self.broker.open_orders,
        )
        features = self._compute_features(tick)
        rejections = self._run_strategies(tick, snapshot=snapshot, as_of=as_of)

        self.journal.record_position_snapshot(snapshot, at=as_of)
        self.journal.record_pnl(snapshot, at=as_of)
        reconciliation = (
            self.reconciler.reconcile(self.portfolio) if self.config.reconcile_each_tick else None
        )
        return TickResult(
            as_of=as_of,
            signals=self.monitor.snapshot().signals,
            fills=fills,
            rejections=rejections,
            snapshot=snapshot,
            features=features,
            reconciliation=reconciliation,
        )

    # -- pipeline steps ---------------------------------------------------

    def _settle_pending(
        self, context: ExecutionContext, *, as_of: datetime
    ) -> tuple[OrderFilled, ...]:
        pre_trade_count = len(self.portfolio.closed_trades)
        virtual_fills = self.broker.process(context=context, now=as_of)
        events: list[OrderFilled] = []
        for virtual_fill in virtual_fills:
            apply_virtual_fill(self.portfolio, virtual_fill)
            self.reconciler.record_fill(virtual_fill)
            self.oms.record_fill(virtual_fill.updated_order)
            submitted_at = self.broker.submitted_at.get(virtual_fill.order.id, as_of)
            event = fill_event(virtual_fill, submitted_at=submitted_at)
            self.monitor.on_filled(event)
            self.journal.record_fill(event)
            events.append(event)
        for trade in self.portfolio.closed_trades[pre_trade_count:]:
            self.journal.record_exit(trade)
        return tuple(events)

    def _compute_features(self, tick: MarketTick) -> FeatureSet | None:
        if not self.config.compute_features or self.feature_engine is None:
            return None
        ctx = FeatureContext(
            as_of=tick.as_of,
            underlying=tick.underlying,
            chain=tick.chain,
            iv_history=tick.iv_history,
            candles=tick.candles,
        )
        self.latest_features = self.feature_engine.compute_all(ctx)
        return self.latest_features

    def _run_strategies(
        self, tick: MarketTick, *, snapshot: PortfolioSnapshot, as_of: datetime
    ) -> tuple[OrderRejected, ...]:
        rejections: list[OrderRejected] = []
        for strategy in self.strategies:
            ctx = StrategyContext(chain=tick.chain, portfolio=snapshot, now=as_of)
            started = time.perf_counter()
            signals = strategy.on_chain(ctx)
            runtime = time.perf_counter() - started
            for signal in signals:
                self.monitor.on_signal(
                    SignalGenerated(
                        signal=signal,
                        strategy_id=strategy.definition.id,
                        runtime_seconds=runtime,
                    )
                )
                self.journal.record_signal(signal, at=as_of)
                rejection = self._route_signal(
                    signal, strategy_id=strategy.definition.id, snapshot=snapshot, as_of=as_of
                )
                if rejection is not None:
                    rejections.append(rejection)
        return tuple(rejections)

    def _route_signal(
        self,
        signal: Signal,
        *,
        strategy_id: str,
        snapshot: PortfolioSnapshot,
        as_of: datetime,
    ) -> OrderRejected | None:
        decision = self.risk_engine.evaluate(snapshot, signal, evaluated_at=as_of)
        self.journal.record_risk(RiskEvaluated(signal=signal, decision=decision))
        if not decision.approved:
            reason = "; ".join(decision.violations) or "risk rejected"
            event = OrderRejected(signal=signal, reason=reason)
            self.monitor.on_rejected(event)
            self.journal.record_rejection(event, at=as_of)
            return event
        for order in self.oms.submit_signal(signal, strategy_id=strategy_id, now=as_of):
            self.monitor.on_submitted(OrderSubmitted(order=order, submitted_at=as_of))
        return None


def _last_prices(chain: OptionChainSnapshot) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for entry in chain.entries:
        if entry.quote is not None:
            prices[entry.contract.tradingsymbol] = entry.quote.last_price
    return prices

"""AlphaQuant Paper Trading Engine.

Runs the same strategies, risk engine, portfolio accounting, and execution
simulator as the backtester — but driven by a real-time market-data feed instead
of a finite event list, and fills orders locally with an order queue and latency.

No broker order APIs and no live orders: the paper broker simulates every fill.
This is the mandatory burn-in stage before a strategy is eligible for live trading.

The engine composes existing building blocks (backtest execution/portfolio, risk,
strategies, feature store) and adds only the real-time concerns: order queue with
latency, market-hours scheduler, monitoring, journal, and reconciliation.
"""

from alphaquant.paper.broker import PaperBroker, PaperBrokerConfig
from alphaquant.paper.engine import MarketDataFeed, PaperEngineConfig, PaperTradingEngine
from alphaquant.paper.events import (
    MarketTick,
    OrderCancelled,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
    PositionClosed,
    RiskEvaluated,
    SignalGenerated,
)
from alphaquant.paper.journal import (
    InMemoryJournalStore,
    JournalStore,
    JSONJournalStore,
    PaperJournal,
)
from alphaquant.paper.monitor import MonitorSnapshot, PaperMonitor
from alphaquant.paper.orders import PaperOMS
from alphaquant.paper.portfolio import PaperPortfolio
from alphaquant.paper.reconciliation import Reconciler, ReconciliationReport
from alphaquant.paper.scheduler import PaperScheduler

__all__ = [
    "InMemoryJournalStore",
    "JSONJournalStore",
    "JournalStore",
    "MarketDataFeed",
    "MarketTick",
    "MonitorSnapshot",
    "OrderCancelled",
    "OrderFilled",
    "OrderRejected",
    "OrderSubmitted",
    "PaperBroker",
    "PaperBrokerConfig",
    "PaperEngineConfig",
    "PaperJournal",
    "PaperMonitor",
    "PaperOMS",
    "PaperPortfolio",
    "PaperScheduler",
    "PaperTradingEngine",
    "PositionClosed",
    "Reconciler",
    "ReconciliationReport",
    "RiskEvaluated",
    "SignalGenerated",
]

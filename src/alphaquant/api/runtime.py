"""Composition-edge adapters: translate the runtime `Container`'s engines into the
dashboard's read-only port shapes (`alphaquant.dashboard.backend`).

Each adapter holds the `Container` itself, not a resolved engine, and only touches
`container.<engine>` inside its Protocol methods — so building `DashboardSources` never
forces engine construction; that happens lazily (and once, via `cached_property`) the
first time something actually reads from a channel.
"""

from datetime import datetime, timedelta

from alphaquant.backtest.statistics import BacktestStatistics, EquityPoint
from alphaquant.core.container import Container
from alphaquant.core.timeutils import now_utc
from alphaquant.dashboard.backend import DashboardSources, KillSwitchStatus
from alphaquant.dashboard.models import DataFeedStatus, ReconciliationStatus, StrategyEntry
from alphaquant.domain import PortfolioSnapshot
from alphaquant.features.context import FeatureContext
from alphaquant.features.models import FeatureSet
from alphaquant.live.heartbeat import HeartbeatState
from alphaquant.live.market_hours import MarketStatus
from alphaquant.live.metrics import LiveMetricsSnapshot
from alphaquant.live.reconnect import ReconnectState
from alphaquant.live.snapshot import MarketSnapshot
from alphaquant.oms.metrics import OMSMetricsSnapshot
from alphaquant.oms.orders import OMSOrder
from alphaquant.paper.monitor import MonitorSnapshot
from alphaquant.research.experiment import Experiment
from alphaquant.risk import RiskDecision
from alphaquant.strategies import catalog_entries

# OMS reconciliation replays broker/ledger state and appends a journal entry on every
# call — cheap once, but the WebSocket broadcaster polls every channel every ~1s
# (`dashboard/config.py:push_interval_seconds`), so it must be throttled here rather
# than recomputed on every poll.
_RECONCILE_INTERVAL = timedelta(seconds=30)


class _LiveSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def live_metrics(self) -> LiveMetricsSnapshot | None:
        return self._container.live_engine.latest_metrics()

    def market_snapshots(self) -> tuple[MarketSnapshot, ...]:
        # Two possible sources: the WebSocket-streaming `LiveMarketDataEngine` (never
        # populated in this deployment -- no Kite streaming client is configured, see
        # `RuntimeOrchestrator`'s scope note) and `RestPricePoller`'s own chain cache
        # (what's actually running). Without this fallback, "Live Market" shows "no
        # feed" forever even while the REST poller is ticking real spot/PCR/ATM data
        # every cycle -- the page was just never wired to read it.
        engine = self._container.live_engine
        snapshots: list[MarketSnapshot] = []
        for name in self._container.settings.data.underlyings:
            snapshot = engine.latest_snapshot(name)
            if snapshot is None:
                snapshot = self._from_rest_poller_cache(name)
            if snapshot is not None:
                snapshots.append(snapshot)
        return tuple(snapshots)

    def _from_rest_poller_cache(self, underlying: str) -> MarketSnapshot | None:
        chain = self._container.live_engine.cache.latest_chain(underlying)
        if chain is None:
            return None
        return MarketSnapshot(
            underlying=underlying,
            timestamp=chain.timestamp,
            market_status=MarketStatus.OPEN,  # the poller only ever ticks during market hours
            spot=chain.spot,
            option_chain=chain,
            feature_context=FeatureContext(as_of=chain.timestamp, underlying=underlying),
        )

    def heartbeat(self) -> HeartbeatState | None:
        return self._container.heartbeat_monitor.state

    def reconnect(self) -> ReconnectState | None:
        return self._container.reconnect_manager.state


class _OMSSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._last_reconciliation: ReconciliationStatus | None = None
        self._last_reconciled_at: datetime | None = None

    def orders(self) -> tuple[OMSOrder, ...]:
        return tuple(self._container.oms_engine.orders.values())

    def oms_metrics(self) -> OMSMetricsSnapshot | None:
        return self._container.oms_engine.metrics_snapshot()

    def kill_switch(self) -> KillSwitchStatus | None:
        switch = self._container.oms_engine.kill_switch
        return KillSwitchStatus(armed=switch.armed, reason=switch.reason)

    def portfolio_snapshot(self) -> PortfolioSnapshot | None:
        return self._container.oms_engine.portfolio.snapshot()

    def equity_curve(self) -> tuple[EquityPoint, ...]:
        return self._container.oms_engine.portfolio.equity_curve

    def reconciliation(self) -> ReconciliationStatus | None:
        now = now_utc()
        if (
            self._last_reconciled_at is not None
            and now - self._last_reconciled_at < _RECONCILE_INTERVAL
        ):
            return self._last_reconciliation
        report = self._container.oms_engine.reconcile(now=now)
        status = ReconciliationStatus(
            reconciled=report.reconciled,
            missing_orders=len(report.missing_orders),
            status_drift=len(report.status_drift),
        )
        self._last_reconciliation = status
        self._last_reconciled_at = now
        return status


class _RiskSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def recent_decisions(self) -> tuple[RiskDecision, ...]:
        return self._container.risk_engine.recent_decisions()


class _FeatureSourceAdapter:
    """Reads `RestPricePoller`'s own computed features -- today's actually-running
    path -- not the older `PaperTradingEngine` stack, which would show nothing
    forever regardless of how much real feature computation happens here."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def latest_features(self) -> FeatureSet | None:
        try:
            poller = self._container.rest_poller
        except Exception:
            # Same rationale as `_DataFeedSourceAdapter.status()`: building the
            # poller needs a configured Kite session, and no credentials configured
            # is a normal state that must not break every other dashboard channel.
            return None
        return poller.latest_features

    def cache_hits(self) -> int:
        return self._container.feature_cache.hits

    def cache_misses(self) -> int:
        return self._container.feature_cache.misses

    def cache_size(self) -> int:
        return len(self._container.feature_cache)


class _PaperSourceAdapter:
    """The dashboard's "Paper Trading" page means "how is paper trading actually
    going" -- today that's `OrderManagementEngine` + `RestPricePoller`, not the
    older `PaperTradingEngine` stack (kept around, tested, but explicitly not part
    of the live tick-driven path -- see the M15 design notes in `container.py`).
    Reading from `paper_engine` here would show real zeros forever regardless of
    how much real paper trading actually happened.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    def monitor(self) -> MonitorSnapshot | None:
        metrics = self._container.oms_engine.metrics_snapshot()
        return MonitorSnapshot(
            submitted=metrics.orders_submitted,
            filled=metrics.orders_filled,
            rejected=metrics.rejections,
            avg_latency_seconds=metrics.average_latency_seconds,
            fill_rate=metrics.fill_ratio,
        )

    def portfolio_snapshot(self) -> PortfolioSnapshot | None:
        return self._container.oms_engine.portfolio.snapshot()


class _PortfolioSourceAdapter:
    """Feeds `DashboardService.metrics()`'s Sharpe/statistics -- distinct from
    `_OMSSourceAdapter.portfolio_snapshot()`, which only supplies the live snapshot.
    Without this, `sources.portfolio` stays unset and Sharpe is permanently 0.0."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def portfolio_snapshot(self) -> PortfolioSnapshot | None:
        return self._container.oms_engine.portfolio.snapshot()

    def session_statistics(self) -> BacktestStatistics | None:
        return self._container.oms_engine.portfolio.session_statistics()


class _ResearchSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def experiments(self) -> tuple[Experiment, ...]:
        return self._container.experiment_store.list_all()


class _ExecutionSourceAdapter:
    """Gate #3 status only — never the gate itself, never a broker handle."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def is_armed(self) -> bool:
        return self._container.live_trading_gate.is_armed

    def live_trading_permitted(self) -> bool:
        return self._container.live_trading_gate.permits_live_trading(self._container.settings)

    def active_broker_name(self) -> str:
        return "kite" if self.live_trading_permitted() else "simulated"


class _DataFeedSourceAdapter:
    """`RestPricePoller`'s own health -- reads the SAME cached_property instance
    `api/app.py` actually starts, not a fresh one."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def status(self) -> DataFeedStatus | None:
        try:
            poller = self._container.rest_poller
        except Exception:
            # Building the poller needs a configured Kite session (it constructs
            # `kite_provider` eagerly); no credentials configured is a completely
            # normal state (e.g. research-mode-only setups) and must not break
            # every other dashboard channel just because this one can't answer.
            return None
        return DataFeedStatus(
            consecutive_failures=poller.consecutive_failures,
            last_error=poller.last_error,
            orphaned_symbols=poller.orphaned_symbols,
        )


class _StrategySourceAdapter:
    """A pure registry read (M14) — unlike every other adapter here, it needs no `Container`
    engine at all; it's wired through `build_dashboard_sources` only for consistency with the
    rest of this module's "every source may be absent unless wired here" shape."""

    def catalog(self) -> tuple[StrategyEntry, ...]:
        return tuple(StrategyEntry(**entry) for entry in catalog_entries())


def build_dashboard_sources(container: Container) -> DashboardSources:
    """The composition edge: wraps `container`'s engines in read-only port adapters."""
    return DashboardSources(
        live=_LiveSourceAdapter(container),
        oms=_OMSSourceAdapter(container),
        portfolio=_PortfolioSourceAdapter(container),
        risk=_RiskSourceAdapter(container),
        features=_FeatureSourceAdapter(container),
        paper=_PaperSourceAdapter(container),
        research=_ResearchSourceAdapter(container),
        execution=_ExecutionSourceAdapter(container),
        strategies=_StrategySourceAdapter(),
        data_feed=_DataFeedSourceAdapter(container),
    )

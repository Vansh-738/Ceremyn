"""Composition-edge adapters: translate the runtime `Container`'s engines into the
dashboard's read-only port shapes (`alphaquant.dashboard.backend`).

Each adapter holds the `Container` itself, not a resolved engine, and only touches
`container.<engine>` inside its Protocol methods — so building `DashboardSources` never
forces engine construction; that happens lazily (and once, via `cached_property`) the
first time something actually reads from a channel.
"""

from datetime import datetime, timedelta

from alphaquant.core.container import Container
from alphaquant.core.timeutils import now_utc
from alphaquant.dashboard.backend import DashboardSources, KillSwitchStatus
from alphaquant.dashboard.models import ReconciliationStatus
from alphaquant.domain import PortfolioSnapshot
from alphaquant.features.models import FeatureSet
from alphaquant.live.heartbeat import HeartbeatState
from alphaquant.live.metrics import LiveMetricsSnapshot
from alphaquant.live.reconnect import ReconnectState
from alphaquant.live.snapshot import MarketSnapshot
from alphaquant.oms.metrics import OMSMetricsSnapshot
from alphaquant.oms.orders import OMSOrder
from alphaquant.paper.monitor import MonitorSnapshot
from alphaquant.research.experiment import Experiment
from alphaquant.risk import RiskDecision

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
        engine = self._container.live_engine
        snapshots = (
            engine.latest_snapshot(name) for name in self._container.settings.data.underlyings
        )
        return tuple(snapshot for snapshot in snapshots if snapshot is not None)

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
    def __init__(self, container: Container) -> None:
        self._container = container

    def latest_features(self) -> FeatureSet | None:
        return self._container.paper_engine.latest_features

    def cache_hits(self) -> int:
        return self._container.feature_cache.hits

    def cache_misses(self) -> int:
        return self._container.feature_cache.misses

    def cache_size(self) -> int:
        return len(self._container.feature_cache)


class _PaperSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def monitor(self) -> MonitorSnapshot | None:
        return self._container.paper_engine.monitor.snapshot()

    def portfolio_snapshot(self) -> PortfolioSnapshot | None:
        return self._container.paper_engine.portfolio.snapshot()


class _ResearchSourceAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def experiments(self) -> tuple[Experiment, ...]:
        return self._container.experiment_store.list_all()


def build_dashboard_sources(container: Container) -> DashboardSources:
    """The composition edge: wraps `container`'s engines in read-only port adapters."""
    return DashboardSources(
        live=_LiveSourceAdapter(container),
        oms=_OMSSourceAdapter(container),
        risk=_RiskSourceAdapter(container),
        features=_FeatureSourceAdapter(container),
        paper=_PaperSourceAdapter(container),
        research=_ResearchSourceAdapter(container),
    )

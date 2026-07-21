"""Read ports and the DashboardService aggregator.

The dashboard depends only on these read-only **port protocols**, never on the concrete
engines — so it is structurally incapable of placing an order or bypassing the OMS. The
composition edge injects adapters (the real engines structurally satisfy the ports). The
service assembles view models by pulling from the ports and delegating to the pure builders.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from ceremyn.backtest.statistics import BacktestStatistics, EquityPoint
from ceremyn.dashboard import views
from ceremyn.dashboard.alerts import derive_alerts
from ceremyn.dashboard.config import DashboardSettings
from ceremyn.dashboard.health import build_health
from ceremyn.dashboard.metrics import build_metrics
from ceremyn.dashboard.models import (
    AlertsView,
    Channel,
    DataFeedStatus,
    EquityHistoryView,
    ExecutionView,
    FeatureStoreView,
    HealthView,
    LiveMarketView,
    LogRow,
    LogsView,
    MetricsView,
    OMSView,
    OrdersView,
    OverviewView,
    PaperView,
    PortfolioView,
    PositionsView,
    ReconciliationStatus,
    ResearchView,
    RiskView,
    StrategyEntry,
    StrategyView,
)
from ceremyn.domain import PortfolioSnapshot
from ceremyn.features.models import FeatureSet
from ceremyn.live.heartbeat import HeartbeatState
from ceremyn.live.metrics import LiveMetricsSnapshot
from ceremyn.live.reconnect import ReconnectState
from ceremyn.live.snapshot import MarketSnapshot
from ceremyn.oms.metrics import OMSMetricsSnapshot
from ceremyn.oms.orders import OMSOrder
from ceremyn.paper.monitor import MonitorSnapshot
from ceremyn.research.experiment import Experiment
from ceremyn.risk import RiskDecision


class KillSwitchStatus(BaseModel):
    """Kill-switch state as read primitives (avoids importing the OMS engine module)."""

    model_config = ConfigDict(frozen=True)

    armed: bool = False
    reason: str = ""


# -- read ports ---------------------------------------------------------------


class LiveSource(Protocol):
    def live_metrics(self) -> LiveMetricsSnapshot | None: ...
    def market_snapshots(self) -> tuple[MarketSnapshot, ...]: ...
    def heartbeat(self) -> HeartbeatState | None: ...
    def reconnect(self) -> ReconnectState | None: ...


class OMSSource(Protocol):
    def orders(self) -> tuple[OMSOrder, ...]: ...
    def oms_metrics(self) -> OMSMetricsSnapshot | None: ...
    def kill_switch(self) -> KillSwitchStatus | None: ...
    def portfolio_snapshot(self) -> PortfolioSnapshot | None: ...
    def reconciliation(self) -> ReconciliationStatus | None: ...
    def equity_curve(self) -> tuple[EquityPoint, ...]: ...


class PortfolioSource(Protocol):
    def portfolio_snapshot(self) -> PortfolioSnapshot | None: ...
    def session_statistics(self) -> BacktestStatistics | None: ...


class RiskSource(Protocol):
    def recent_decisions(self) -> tuple[RiskDecision, ...]: ...


class FeatureSource(Protocol):
    def latest_features(self) -> FeatureSet | None: ...
    def cache_hits(self) -> int: ...
    def cache_misses(self) -> int: ...
    def cache_size(self) -> int: ...


class PaperSource(Protocol):
    def monitor(self) -> MonitorSnapshot | None: ...
    def portfolio_snapshot(self) -> PortfolioSnapshot | None: ...


class ResearchSource(Protocol):
    def experiments(self) -> tuple[Experiment, ...]: ...


class LogSource(Protocol):
    def recent_logs(self, limit: int) -> tuple[LogRow, ...]: ...


class DataFeedSource(Protocol):
    """`RestPricePoller`'s own health -- a broken feed (e.g. an expired Kite access
    token) should be a visible alert, not something only ever found in the logs."""

    def status(self) -> DataFeedStatus | None: ...


class ExecutionSource(Protocol):
    """Gate #3 status only — never a broker handle, never order-affecting."""

    def is_armed(self) -> bool: ...
    def live_trading_permitted(self) -> bool: ...
    def active_broker_name(self) -> str: ...


class StrategySource(Protocol):
    """A read-only catalog of registered strategy types — never an engine, never a broker."""

    def catalog(self) -> tuple[StrategyEntry, ...]: ...


@dataclass(frozen=True)
class DashboardSources:
    """The set of read ports wired at the composition edge. Any may be absent."""

    live: LiveSource | None = None
    oms: OMSSource | None = None
    portfolio: PortfolioSource | None = None
    risk: RiskSource | None = None
    features: FeatureSource | None = None
    paper: PaperSource | None = None
    research: ResearchSource | None = None
    logs: LogSource | None = None
    execution: ExecutionSource | None = None
    strategies: StrategySource | None = None
    data_feed: DataFeedSource | None = None


class DashboardService:
    def __init__(
        self, sources: DashboardSources, settings: DashboardSettings | None = None
    ) -> None:
        self.sources = sources
        self.settings = settings or DashboardSettings()

    # -- shared helpers ---------------------------------------------------

    def _portfolio_snapshot(self) -> PortfolioSnapshot | None:
        for source in (self.sources.oms, self.sources.portfolio, self.sources.paper):
            if source is not None:
                snapshot = source.portfolio_snapshot()
                if snapshot is not None:
                    return snapshot
        return None

    def _kill_switch(self) -> KillSwitchStatus:
        if self.sources.oms is not None:
            status = self.sources.oms.kill_switch()
            if status is not None:
                return status
        return KillSwitchStatus()

    # -- per-view assembly ------------------------------------------------

    def portfolio(self) -> PortfolioView:
        return views.build_portfolio(self._portfolio_snapshot())

    def equity_history(self) -> EquityHistoryView:
        curve = self.sources.oms.equity_curve() if self.sources.oms is not None else ()
        return views.build_equity_history(curve)

    def orders(self, *, page: int = 1, page_size: int | None = None) -> OrdersView:
        orders = self.sources.oms.orders() if self.sources.oms is not None else ()
        return views.build_orders(orders, page=page, page_size=page_size or self.settings.page_size)

    def positions(self) -> PositionsView:
        return views.build_positions(self._portfolio_snapshot())

    def live(self) -> LiveMarketView:
        if self.sources.live is None:
            return LiveMarketView()
        return views.build_live(
            self.sources.live.live_metrics(), self.sources.live.market_snapshots()
        )

    def features(self) -> FeatureStoreView:
        source = self.sources.features
        if source is None:
            return FeatureStoreView()
        return views.build_features(
            source.latest_features(),
            hits=source.cache_hits(),
            misses=source.cache_misses(),
            size=source.cache_size(),
        )

    def risk(self) -> RiskView:
        decisions = self.sources.risk.recent_decisions() if self.sources.risk else ()
        return views.build_risk(decisions)

    def oms(self) -> OMSView:
        source = self.sources.oms
        kill = self._kill_switch()
        return views.build_oms(
            source.oms_metrics() if source else None,
            kill_switch_armed=kill.armed,
            kill_switch_reason=kill.reason,
            reconciliation=source.reconciliation() if source else None,
        )

    def research(self) -> ResearchView:
        experiments = self.sources.research.experiments() if self.sources.research else ()
        return views.build_research(experiments)

    def paper(self) -> PaperView:
        source = self.sources.paper
        return views.build_paper(
            source.monitor() if source else None,
            source.portfolio_snapshot() if source else None,
        )

    def logs(self) -> LogsView:
        source = self.sources.logs
        logs = source.recent_logs(self.settings.page_size) if source else ()
        return views.build_logs(logs)

    def execution(self) -> ExecutionView:
        source = self.sources.execution
        if source is None:
            return ExecutionView()
        return views.build_execution(
            armed=source.is_armed(),
            live_trading_permitted=source.live_trading_permitted(),
            active_broker=source.active_broker_name(),
        )

    def strategies(self) -> StrategyView:
        source = self.sources.strategies
        entries = source.catalog() if source is not None else ()
        return StrategyView(strategies=entries)

    def metrics(self) -> MetricsView:
        oms_metrics = self.sources.oms.oms_metrics() if self.sources.oms else None
        live_metrics = self.sources.live.live_metrics() if self.sources.live else None
        stats = self.sources.portfolio.session_statistics() if self.sources.portfolio else None
        return build_metrics(
            portfolio=self._portfolio_snapshot(),
            oms_metrics=oms_metrics,
            live_metrics=live_metrics,
            open_orders=self.orders().open_count,
            statistics=stats,
            feature_cache_hit_rate=self.features().cache_hit_rate,
            experiment_count=self.research().experiment_count,
        )

    def alerts(self) -> AlertsView:
        kill = self._kill_switch()
        oms = self.sources.oms
        live = self.sources.live
        data_feed = self.sources.data_feed
        return AlertsView(
            alerts=derive_alerts(
                risk_decisions=(self.sources.risk.recent_decisions() if self.sources.risk else ()),
                orders=oms.orders() if oms else (),
                oms_metrics=oms.oms_metrics() if oms else None,
                kill_switch_armed=kill.armed,
                kill_switch_reason=kill.reason,
                heartbeat=live.heartbeat() if live else None,
                reconnect=live.reconnect() if live else None,
                reconciliation=oms.reconciliation() if oms else None,
                data_feed_status=data_feed.status() if data_feed else None,
            )
        )

    def health(self) -> HealthView:
        live = self.sources.live
        oms = self.sources.oms
        data_feed = self.sources.data_feed
        return build_health(
            heartbeat=live.heartbeat() if live else None,
            reconnect=live.reconnect() if live else None,
            live_metrics=live.live_metrics() if live else None,
            oms_metrics=oms.oms_metrics() if oms else None,
            components_present={
                "live": self.sources.live is not None,
                "oms": self.sources.oms is not None,
                "paper": self.sources.paper is not None,
                "features": self.sources.features is not None,
                "research": self.sources.research is not None,
                "risk": self.sources.risk is not None,
            },
            data_feed_status=data_feed.status() if data_feed else None,
        )

    def overview(self) -> OverviewView:
        portfolio = self._portfolio_snapshot()
        orders = self.orders()
        oms_metrics = self.sources.oms.oms_metrics() if self.sources.oms else None
        heartbeat = self.sources.live.heartbeat() if self.sources.live else None
        kill = self._kill_switch()
        return OverviewView(
            net_pnl=(
                float(portfolio.realized_pnl + portfolio.unrealized_pnl)
                if portfolio is not None
                else 0.0
            ),
            drawdown=float(portfolio.drawdown) if portfolio is not None else 0.0,
            open_orders=orders.open_count,
            fill_ratio=oms_metrics.fill_ratio if oms_metrics is not None else 0.0,
            heartbeat_healthy=heartbeat.is_healthy if heartbeat is not None else True,
            kill_switch_armed=kill.armed,
            alert_count=self.alerts().count,
            experiment_count=self.research().experiment_count,
        )

    # -- channel dispatch (REST + WebSocket share this) -------------------

    def channel_payload(self, channel: Channel) -> dict[str, Any]:
        return self._view_for(channel).model_dump(mode="json")

    def _view_for(self, channel: Channel) -> BaseModel:
        dispatch: dict[Channel, Callable[..., BaseModel]] = {
            Channel.OVERVIEW: self.overview,
            Channel.PORTFOLIO: self.portfolio,
            Channel.ORDERS: self.orders,
            Channel.POSITIONS: self.positions,
            Channel.LIVE: self.live,
            Channel.FEATURES: self.features,
            Channel.RISK: self.risk,
            Channel.OMS: self.oms,
            Channel.RESEARCH: self.research,
            Channel.PAPER: self.paper,
            Channel.HEALTH: self.health,
            Channel.LOGS: self.logs,
            Channel.METRICS: self.metrics,
            Channel.ALERTS: self.alerts,
            Channel.EXECUTION: self.execution,
            Channel.STRATEGIES: self.strategies,
        }
        return dispatch[channel]()

"""Dashboard view models: frozen DTOs returned by the API and pushed over the WebSocket.

Pure data — every field is mapped from an existing engine snapshot. No business logic.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Channel(StrEnum):
    """WebSocket channels; also the REST view keys."""

    OVERVIEW = "overview"
    PORTFOLIO = "portfolio"
    ORDERS = "orders"
    POSITIONS = "positions"
    LIVE = "live"
    FEATURES = "features"
    RISK = "risk"
    OMS = "oms"
    RESEARCH = "research"
    PAPER = "paper"
    HEALTH = "health"
    LOGS = "logs"
    METRICS = "metrics"
    ALERTS = "alerts"
    EXECUTION = "execution"
    STRATEGIES = "strategies"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(StrEnum):
    RISK_VIOLATION = "risk_violation"
    OMS_FAILURE = "oms_failure"
    RECONNECT_FAILURE = "reconnect_failure"
    BROKER_DISCONNECT = "broker_disconnect"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    KILL_SWITCH = "kill_switch"


class Alert(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: AlertSeverity
    category: AlertCategory
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AlertsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    alerts: tuple[Alert, ...] = ()

    @property
    def count(self) -> int:
        return len(self.alerts)


class GreeksView(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0


class ExposureView(BaseModel):
    model_config = ConfigDict(frozen=True)

    gross_notional: float = 0.0
    net_notional: float = 0.0
    short_option_units: int = 0
    net_option_units: int = 0
    by_underlying: dict[str, float] = Field(default_factory=dict)


class PortfolioView(BaseModel):
    model_config = ConfigDict(frozen=True)

    buying_power: float = 0.0
    margin_used: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    drawdown: float = 0.0
    kill_switch_state: str = "disarmed"
    position_count: int = 0
    greeks: GreeksView = Field(default_factory=GreeksView)
    exposure: ExposureView = Field(default_factory=ExposureView)


class OrderRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    oms_order_id: str
    tradingsymbol: str
    side: str
    quantity: int
    filled_quantity: int
    execution_state: str
    broker_name: str | None = None
    average_fill_price: float | None = None
    retry_count: int = 0
    last_error: str = ""
    updated_at: datetime


class OrdersView(BaseModel):
    model_config = ConfigDict(frozen=True)

    orders: tuple[OrderRow, ...] = ()
    total: int = 0
    page: int = 1
    page_size: int = 50
    open_count: int = 0
    filled_count: int = 0
    rejected_count: int = 0


class PositionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    tradingsymbol: str
    underlying: str
    quantity: int
    avg_price: float
    direction: str  # long / short


class PositionsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    positions: tuple[PositionRow, ...] = ()
    long_count: int = 0
    short_count: int = 0


class UnderlyingMarketRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying: str
    market_status: str
    spot: float
    latency_ms: float
    source_tick_count: int
    atm_strike: float | None = None
    pcr: float | None = None
    timestamp: datetime


class LiveMarketView(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlyings: tuple[UnderlyingMarketRow, ...] = ()
    messages_per_second: float = 0.0
    reconnect_count: int = 0
    heartbeat_delay_seconds: float = 0.0


class FeatureStoreView(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature_set_version: str | None = None
    feature_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_size: int = 0
    cache_hit_rate: float = 0.0
    sample: dict[str, str] = Field(default_factory=dict)


class RiskDecisionRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    risk_score: float
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    at: datetime


class RiskView(BaseModel):
    model_config = ConfigDict(frozen=True)

    decisions: tuple[RiskDecisionRow, ...] = ()
    violation_count: int = 0
    latest_score: float | None = None


class ReconciliationStatus(BaseModel):
    """Reconciliation outcome as read primitives (avoids importing oms.reconciliation,
    which transitively depends on the broker adapter)."""

    model_config = ConfigDict(frozen=True)

    reconciled: bool = True
    missing_orders: int = 0
    status_drift: int = 0
    position_drift: int = 0

    @property
    def drift_count(self) -> int:
        return self.missing_orders + self.status_drift + self.position_drift


class OMSView(BaseModel):
    model_config = ConfigDict(frozen=True)

    orders_submitted: int = 0
    orders_filled: int = 0
    partial_fills: int = 0
    rejections: int = 0
    retry_count: int = 0
    fill_ratio: float = 0.0
    broker_latency_seconds: float = 0.0
    p95_latency_seconds: float = 0.0
    p99_latency_seconds: float = 0.0
    broker_uptime_ratio: float = 1.0
    kill_switch_armed: bool = False
    kill_switch_reason: str = ""
    reconciled: bool = True
    reconciliation_drift: int = 0


class ExperimentRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int
    experiment_id: str
    strategy_name: str
    sharpe: float
    total_return: float
    max_drawdown: float
    trade_count: int


class ResearchView(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_count: int = 0
    leaderboard: tuple[ExperimentRow, ...] = ()


class PaperView(BaseModel):
    model_config = ConfigDict(frozen=True)

    submitted: int = 0
    filled: int = 0
    rejected: int = 0
    cancelled: int = 0
    fill_rate: float = 0.0
    avg_latency_seconds: float = 0.0
    max_latency_seconds: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class ComponentHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    healthy: bool
    detail: str = ""


class HealthView(BaseModel):
    model_config = ConfigDict(frozen=True)

    heartbeat_healthy: bool = True
    heartbeat_delay_seconds: float = 0.0
    reconnect_attempts: int = 0
    is_reconnecting: bool = False
    broker_uptime_ratio: float = 1.0
    messages_per_second: float = 0.0
    components: tuple[ComponentHealth, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.heartbeat_healthy and all(c.healthy for c in self.components)


class LogRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    level: str
    event: str
    context: dict[str, str] = Field(default_factory=dict)


class LogsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    logs: tuple[LogRow, ...] = ()


class MetricsView(BaseModel):
    """The flat M11 metric catalog."""

    model_config = ConfigDict(frozen=True)

    pnl: float = 0.0
    drawdown: float = 0.0
    sharpe: float = 0.0
    greeks: GreeksView = Field(default_factory=GreeksView)
    gross_exposure: float = 0.0
    open_orders: int = 0
    filled_orders: int = 0
    rejected_orders: int = 0
    broker_latency_seconds: float = 0.0
    reconnect_count: int = 0
    heartbeat_delay_seconds: float = 0.0
    feature_cache_hit_rate: float = 0.0
    experiment_count: int = 0


class ExecutionView(BaseModel):
    """Gate #3 (runtime arming) status only — read-only, never a broker or order type."""

    model_config = ConfigDict(frozen=True)

    armed: bool = False
    live_trading_permitted: bool = False
    active_broker: str = "simulated"


class StrategyEntry(BaseModel):
    """One registered strategy type: the same catalog the LLM assistant reads, surfaced for
    the dashboard (M14)."""

    model_config = ConfigDict(frozen=True)

    strategy_type: str
    class_name: str
    description: str = ""
    params_schema: dict[str, Any] = Field(default_factory=dict)


class StrategyView(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategies: tuple[StrategyEntry, ...] = ()


class OverviewView(BaseModel):
    model_config = ConfigDict(frozen=True)

    net_pnl: float = 0.0
    drawdown: float = 0.0
    open_orders: int = 0
    fill_ratio: float = 0.0
    heartbeat_healthy: bool = True
    kill_switch_armed: bool = False
    alert_count: int = 0
    experiment_count: int = 0


class WSFrame(BaseModel):
    """A WebSocket message envelope."""

    model_config = ConfigDict(frozen=True)

    kind: str  # "snapshot" | "event" | "ping" | "ack" | "error"
    channel: str
    payload: dict[str, Any] = Field(default_factory=dict)

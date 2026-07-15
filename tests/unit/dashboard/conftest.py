from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphaquant.backtest.statistics import BacktestStatistics
from alphaquant.dashboard.backend import DashboardService, DashboardSources, KillSwitchStatus
from alphaquant.dashboard.models import LogRow, ReconciliationStatus
from alphaquant.domain import (
    Order,
    PortfolioExposure,
    PortfolioGreeks,
    PortfolioSnapshot,
    Position,
)
from alphaquant.domain.enums import KillSwitchState, OrderType, Side
from alphaquant.features.context import FeatureContext
from alphaquant.features.models import FeatureSet, FeatureValue
from alphaquant.live.heartbeat import HeartbeatState
from alphaquant.live.market_hours import MarketStatus
from alphaquant.live.metrics import LiveMetrics
from alphaquant.live.reconnect import ReconnectState
from alphaquant.live.snapshot import MarketSnapshot
from alphaquant.oms.metrics import OMSMetrics
from alphaquant.oms.orders import OMSExecutionState, OMSOrder
from alphaquant.paper.monitor import PaperMonitor
from alphaquant.risk import RiskDecision
from tests.unit.backtest.helpers import make_chain, make_contract

NOW = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)


# -- snapshot builders --------------------------------------------------------


def make_oms_order(
    *,
    state: OMSExecutionState = OMSExecutionState.PENDING,
    side: Side = Side.BUY,
    filled: int = 0,
    last_error: str = "",
) -> OMSOrder:
    return OMSOrder(
        plan_id=uuid4(),
        intent_id=uuid4(),
        request_hash="hash",
        strategy_id="strategy",
        order=Order(
            contract=make_contract(),
            side=side,
            quantity=25,
            order_type=OrderType.MARKET,
            created_at=NOW,
        ),
        execution_state=state,
        broker_name="paper",
        filled_quantity=filled,
        last_error=last_error,
        created_at=NOW,
        updated_at=NOW,
    )


def make_portfolio_snapshot(
    *,
    realized: str = "1000",
    unrealized: str = "250",
    drawdown: str = "300",
    kill: KillSwitchState = KillSwitchState.DISARMED,
    positions: tuple[Position, ...] = (),
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        positions=positions,
        buying_power=Decimal("900000"),
        margin_used=Decimal("100000"),
        realized_pnl=Decimal(realized),
        unrealized_pnl=Decimal(unrealized),
        daily_pnl=Decimal("1250"),
        drawdown=Decimal(drawdown),
        portfolio_greeks=PortfolioGreeks(delta=0.5, gamma=0.01, theta=-12.0, vega=8.0, rho=1.0),
        exposure=PortfolioExposure(
            gross_notional=Decimal("500000"),
            net_notional=Decimal("100000"),
            short_option_units=25,
            net_option_units=25,
            by_underlying={"NIFTY": Decimal("100000")},
        ),
        kill_switch_state=kill,
    )


def make_position(strike: int = 24000, quantity: int = 25) -> Position:
    return Position(
        contract=make_contract(strike=str(strike)),
        quantity=quantity,
        avg_price=Decimal("150"),
    )


def make_market_snapshot() -> MarketSnapshot:
    chain = make_chain(timestamp=NOW, last_price="180", bid="179", ask="181")
    return MarketSnapshot(
        underlying="NIFTY",
        timestamp=NOW,
        market_status=MarketStatus.OPEN,
        spot=Decimal("24010"),
        option_chain=chain,
        feature_context=FeatureContext(as_of=NOW, underlying="NIFTY", chain=chain),
        source_tick_count=42,
        latency_ms=12.5,
    )


def make_feature_set() -> FeatureSet:
    return FeatureSet(
        as_of=NOW,
        underlying="NIFTY",
        feature_set_version="abc123",
        context_fingerprint="fp",
        values={
            "pcr": FeatureValue(name="pcr", version="1", value=1.2, as_of=NOW),
            "market_regime": FeatureValue(
                name="market_regime", version="1", value="trending", as_of=NOW
            ),
        },
    )


def make_risk_decision(*, approved: bool = True, score: float = 90.0) -> RiskDecision:
    return RiskDecision(
        approved=approved,
        risk_score=score,
        violations=() if approved else ("max_lots_per_signal exceeded",),
        warnings=(),
        timestamp=NOW,
    )


def make_oms_metrics() -> OMSMetrics:
    metrics = OMSMetrics()
    metrics.record_submission(0.12, broker_latency_seconds=0.04)
    metrics.record_fill(partial=False)
    return metrics


# -- fake sources -------------------------------------------------------------


class FakeLive:
    def __init__(self, *, healthy: bool = True, reconnecting: bool = False) -> None:
        self._metrics = LiveMetrics()
        self._metrics.record_tick(NOW, latency_ms=5.0)
        self._metrics.record_reconnect()
        self._healthy = healthy
        self._reconnecting = reconnecting

    def live_metrics(self):  # type: ignore[no-untyped-def]
        return self._metrics.snapshot(NOW)

    def market_snapshots(self):  # type: ignore[no-untyped-def]
        return (make_market_snapshot(),)

    def heartbeat(self):  # type: ignore[no-untyped-def]
        return HeartbeatState(is_healthy=self._healthy, last_seen_at=NOW, delay_seconds=1.0)

    def reconnect(self):  # type: ignore[no-untyped-def]
        return ReconnectState(
            attempts=2 if self._reconnecting else 0, is_reconnecting=self._reconnecting
        )


class FakeOMS:
    def __init__(
        self,
        *,
        orders: tuple[OMSOrder, ...] = (),
        kill_armed: bool = False,
        reconciled: bool = True,
        portfolio: PortfolioSnapshot | None = None,
    ) -> None:
        self._orders = orders
        self._metrics = make_oms_metrics()
        self._kill = KillSwitchStatus(armed=kill_armed, reason="loss limit" if kill_armed else "")
        self._recon = ReconciliationStatus(
            reconciled=reconciled, position_drift=0 if reconciled else 1
        )
        self._portfolio = portfolio

    def orders(self):  # type: ignore[no-untyped-def]
        return self._orders

    def oms_metrics(self):  # type: ignore[no-untyped-def]
        return self._metrics.snapshot(NOW)

    def kill_switch(self):  # type: ignore[no-untyped-def]
        return self._kill

    def portfolio_snapshot(self):  # type: ignore[no-untyped-def]
        return self._portfolio

    def reconciliation(self):  # type: ignore[no-untyped-def]
        return self._recon


class FakePortfolio:
    def __init__(self, snapshot: PortfolioSnapshot | None) -> None:
        self._snapshot = snapshot

    def portfolio_snapshot(self):  # type: ignore[no-untyped-def]
        return self._snapshot

    def session_statistics(self):  # type: ignore[no-untyped-def]
        return BacktestStatistics(sharpe=1.85)


class FakeRisk:
    def __init__(self, decisions: tuple[RiskDecision, ...]) -> None:
        self._decisions = decisions

    def recent_decisions(self):  # type: ignore[no-untyped-def]
        return self._decisions


class FakeFeatures:
    def latest_features(self):  # type: ignore[no-untyped-def]
        return make_feature_set()

    def cache_hits(self) -> int:
        return 8

    def cache_misses(self) -> int:
        return 2

    def cache_size(self) -> int:
        return 10


class FakePaper:
    def __init__(self) -> None:
        self._monitor = PaperMonitor()

    def monitor(self):  # type: ignore[no-untyped-def]
        return self._monitor.snapshot()

    def portfolio_snapshot(self):  # type: ignore[no-untyped-def]
        return make_portfolio_snapshot()


class FakeResearch:
    def __init__(self, experiments: tuple = ()) -> None:  # type: ignore[type-arg]
        self._experiments = experiments

    def experiments(self):  # type: ignore[no-untyped-def]
        return self._experiments


class FakeLogs:
    def recent_logs(self, limit: int) -> tuple[LogRow, ...]:
        return (
            LogRow(timestamp=NOW, level="info", event="engine_started", context={"mode": "paper"}),
        )[:limit]


class FakeExecution:
    def __init__(self, *, armed: bool = False, permitted: bool = False) -> None:
        self._armed = armed
        self._permitted = permitted

    def is_armed(self) -> bool:
        return self._armed

    def live_trading_permitted(self) -> bool:
        return self._permitted

    def active_broker_name(self) -> str:
        return "kite" if self._permitted else "simulated"


@pytest.fixture
def full_sources() -> DashboardSources:
    return DashboardSources(
        live=FakeLive(),
        oms=FakeOMS(
            orders=(
                make_oms_order(state=OMSExecutionState.PENDING),
                make_oms_order(state=OMSExecutionState.FILLED, filled=25),
                make_oms_order(state=OMSExecutionState.REJECTED, last_error="broker down"),
            ),
            portfolio=make_portfolio_snapshot(),
        ),
        portfolio=FakePortfolio(make_portfolio_snapshot()),
        risk=FakeRisk((make_risk_decision(approved=True),)),
        features=FakeFeatures(),
        paper=FakePaper(),
        research=FakeResearch(),
        logs=FakeLogs(),
        execution=FakeExecution(),
    )


@pytest.fixture
def service(full_sources: DashboardSources) -> DashboardService:
    return DashboardService(full_sources)

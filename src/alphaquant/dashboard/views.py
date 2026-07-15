"""Pure view assemblers: existing engine snapshots -> frozen view models.

No I/O, no business logic — only selection and mapping. Each builder takes exactly the
snapshots it needs so it is trivially unit-testable with fakes.
"""

from decimal import Decimal

from alphaquant.dashboard.models import (
    ExecutionView,
    ExperimentRow,
    ExposureView,
    FeatureStoreView,
    GreeksView,
    LiveMarketView,
    LogRow,
    LogsView,
    OMSView,
    OrderRow,
    OrdersView,
    PaperView,
    PortfolioView,
    PositionRow,
    PositionsView,
    ReconciliationStatus,
    ResearchView,
    RiskDecisionRow,
    RiskView,
    UnderlyingMarketRow,
)
from alphaquant.domain import PortfolioSnapshot
from alphaquant.features.models import FeatureSet
from alphaquant.live.metrics import LiveMetricsSnapshot
from alphaquant.live.snapshot import MarketSnapshot
from alphaquant.oms.metrics import OMSMetricsSnapshot
from alphaquant.oms.orders import OMSExecutionState, OMSOrder
from alphaquant.paper.monitor import MonitorSnapshot
from alphaquant.research.experiment import Experiment
from alphaquant.research.leaderboard import Leaderboard, RankMetric
from alphaquant.risk import RiskDecision

_OPEN_STATES = frozenset(
    {
        OMSExecutionState.NEW,
        OMSExecutionState.VALIDATED,
        OMSExecutionState.ROUTED,
        OMSExecutionState.PENDING,
        OMSExecutionState.PARTIALLY_FILLED,
        OMSExecutionState.CANCEL_PENDING,
    }
)
_REJECTED_STATES = frozenset(
    {OMSExecutionState.REJECTED, OMSExecutionState.FAILED, OMSExecutionState.EXPIRED}
)


def _f(value: Decimal | float) -> float:
    return float(value)


def build_portfolio(snapshot: PortfolioSnapshot | None) -> PortfolioView:
    if snapshot is None:
        return PortfolioView()
    greeks = snapshot.portfolio_greeks
    exposure = snapshot.exposure
    return PortfolioView(
        buying_power=_f(snapshot.buying_power),
        margin_used=_f(snapshot.margin_used),
        realized_pnl=_f(snapshot.realized_pnl),
        unrealized_pnl=_f(snapshot.unrealized_pnl),
        daily_pnl=_f(snapshot.daily_pnl),
        drawdown=_f(snapshot.drawdown),
        kill_switch_state=snapshot.kill_switch_state.value,
        position_count=len(snapshot.positions),
        greeks=GreeksView(
            delta=greeks.delta,
            gamma=greeks.gamma,
            theta=greeks.theta,
            vega=greeks.vega,
            rho=greeks.rho,
        ),
        exposure=ExposureView(
            gross_notional=_f(exposure.gross_notional),
            net_notional=_f(exposure.net_notional),
            short_option_units=exposure.short_option_units,
            net_option_units=exposure.net_option_units,
            by_underlying={k: _f(v) for k, v in exposure.by_underlying.items()},
        ),
    )


def build_orders(orders: tuple[OMSOrder, ...], *, page: int, page_size: int) -> OrdersView:
    ordered = sorted(orders, key=lambda o: o.updated_at, reverse=True)
    start = (page - 1) * page_size
    rows = tuple(
        OrderRow(
            oms_order_id=str(order.oms_order_id),
            tradingsymbol=order.order.contract.tradingsymbol,
            side=order.order.side.value,
            quantity=order.order.quantity,
            filled_quantity=order.filled_quantity,
            execution_state=order.execution_state.value,
            broker_name=order.broker_name,
            average_fill_price=(
                _f(order.average_fill_price) if order.average_fill_price is not None else None
            ),
            retry_count=order.retry_count,
            last_error=order.last_error,
            updated_at=order.updated_at,
        )
        for order in ordered[start : start + page_size]
    )
    return OrdersView(
        orders=rows,
        total=len(orders),
        page=page,
        page_size=page_size,
        open_count=sum(1 for o in orders if o.execution_state in _OPEN_STATES),
        filled_count=sum(1 for o in orders if o.execution_state is OMSExecutionState.FILLED),
        rejected_count=sum(1 for o in orders if o.execution_state in _REJECTED_STATES),
    )


def build_positions(snapshot: PortfolioSnapshot | None) -> PositionsView:
    if snapshot is None:
        return PositionsView()
    rows: list[PositionRow] = []
    longs = shorts = 0
    for position in snapshot.positions:
        if position.is_flat:
            continue
        direction = "long" if position.is_long else "short"
        if position.is_long:
            longs += 1
        else:
            shorts += 1
        rows.append(
            PositionRow(
                tradingsymbol=position.contract.tradingsymbol,
                underlying=position.contract.underlying,
                quantity=position.quantity,
                avg_price=_f(position.avg_price),
                direction=direction,
            )
        )
    return PositionsView(positions=tuple(rows), long_count=longs, short_count=shorts)


def build_live(
    metrics: LiveMetricsSnapshot | None,
    market_snapshots: tuple[MarketSnapshot, ...],
) -> LiveMarketView:
    rows = tuple(
        UnderlyingMarketRow(
            underlying=snapshot.underlying,
            market_status=snapshot.market_status.value,
            spot=_f(snapshot.spot),
            latency_ms=snapshot.latency_ms,
            source_tick_count=snapshot.source_tick_count,
            atm_strike=_f(snapshot.option_chain.atm_strike),
            pcr=snapshot.option_chain.pcr,
            timestamp=snapshot.timestamp,
        )
        for snapshot in market_snapshots
    )
    return LiveMarketView(
        underlyings=rows,
        messages_per_second=metrics.messages_per_second if metrics else 0.0,
        reconnect_count=metrics.reconnect_count if metrics else 0,
        heartbeat_delay_seconds=metrics.heartbeat_delay_seconds if metrics else 0.0,
    )


def build_features(
    features: FeatureSet | None, *, hits: int, misses: int, size: int
) -> FeatureStoreView:
    total = hits + misses
    sample: dict[str, str] = {}
    if features is not None:
        for name in features.names[:8]:
            value = features.values[name].value
            sample[name] = "null" if value is None else str(value)
    return FeatureStoreView(
        feature_set_version=features.feature_set_version if features else None,
        feature_count=len(features.values) if features else 0,
        cache_hits=hits,
        cache_misses=misses,
        cache_size=size,
        cache_hit_rate=round(hits / total, 6) if total else 0.0,
        sample=sample,
    )


def build_risk(decisions: tuple[RiskDecision, ...]) -> RiskView:
    rows = tuple(
        RiskDecisionRow(
            approved=decision.approved,
            risk_score=decision.risk_score,
            violations=decision.violations,
            warnings=decision.warnings,
            at=decision.timestamp,
        )
        for decision in decisions
    )
    violation_count = sum(len(decision.violations) for decision in decisions)
    latest_score = decisions[-1].risk_score if decisions else None
    return RiskView(decisions=rows, violation_count=violation_count, latest_score=latest_score)


def build_oms(
    metrics: OMSMetricsSnapshot | None,
    *,
    kill_switch_armed: bool,
    kill_switch_reason: str,
    reconciliation: ReconciliationStatus | None,
) -> OMSView:
    drift = 0
    reconciled = True
    if reconciliation is not None:
        reconciled = reconciliation.reconciled
        drift = reconciliation.drift_count
    if metrics is None:
        return OMSView(
            kill_switch_armed=kill_switch_armed,
            kill_switch_reason=kill_switch_reason,
            reconciled=reconciled,
            reconciliation_drift=drift,
        )
    return OMSView(
        orders_submitted=metrics.orders_submitted,
        orders_filled=metrics.orders_filled,
        partial_fills=metrics.partial_fills,
        rejections=metrics.rejections,
        retry_count=metrics.retry_count,
        fill_ratio=metrics.fill_ratio,
        broker_latency_seconds=metrics.broker_latency_seconds,
        p95_latency_seconds=metrics.p95_latency_seconds,
        p99_latency_seconds=metrics.p99_latency_seconds,
        broker_uptime_ratio=metrics.broker_uptime_ratio,
        kill_switch_armed=kill_switch_armed,
        kill_switch_reason=kill_switch_reason,
        reconciled=reconciled,
        reconciliation_drift=drift,
    )


def build_research(experiments: tuple[Experiment, ...], *, limit: int = 10) -> ResearchView:
    ranked = Leaderboard().rank(experiments, by=RankMetric.SHARPE)[:limit]
    rows = tuple(
        ExperimentRow(
            rank=row.rank,
            experiment_id=row.experiment_id,
            strategy_name=row.strategy_name,
            sharpe=row.sharpe,
            total_return=row.total_return,
            max_drawdown=row.max_drawdown,
            trade_count=row.trade_count,
        )
        for row in ranked
    )
    return ResearchView(experiment_count=len(experiments), leaderboard=rows)


def build_paper(monitor: MonitorSnapshot | None, snapshot: PortfolioSnapshot | None) -> PaperView:
    if monitor is None:
        return PaperView(
            realized_pnl=_f(snapshot.realized_pnl) if snapshot else 0.0,
            unrealized_pnl=_f(snapshot.unrealized_pnl) if snapshot else 0.0,
        )
    return PaperView(
        submitted=monitor.submitted,
        filled=monitor.filled,
        rejected=monitor.rejected,
        cancelled=monitor.cancelled,
        fill_rate=monitor.fill_rate,
        avg_latency_seconds=monitor.avg_latency_seconds,
        max_latency_seconds=monitor.max_latency_seconds,
        realized_pnl=_f(snapshot.realized_pnl) if snapshot else 0.0,
        unrealized_pnl=_f(snapshot.unrealized_pnl) if snapshot else 0.0,
    )


def build_logs(logs: tuple[LogRow, ...]) -> LogsView:
    return LogsView(logs=logs)


def build_execution(
    *, armed: bool, live_trading_permitted: bool, active_broker: str
) -> ExecutionView:
    return ExecutionView(
        armed=armed, live_trading_permitted=live_trading_permitted, active_broker=active_broker
    )

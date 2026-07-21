"""Pure alert derivation from current system state.

Each alert is a classification of existing state — the dashboard never changes state.
"""

from ceremyn.dashboard.models import (
    Alert,
    AlertCategory,
    AlertSeverity,
    DataFeedStatus,
    ReconciliationStatus,
)
from ceremyn.live.heartbeat import HeartbeatState
from ceremyn.live.reconnect import ReconnectState
from ceremyn.oms.metrics import OMSMetricsSnapshot
from ceremyn.oms.orders import OMSExecutionState, OMSOrder
from ceremyn.risk import RiskDecision

_FAILED_STATES = frozenset({OMSExecutionState.FAILED, OMSExecutionState.REJECTED})


def derive_alerts(
    *,
    risk_decisions: tuple[RiskDecision, ...] = (),
    orders: tuple[OMSOrder, ...] = (),
    oms_metrics: OMSMetricsSnapshot | None = None,
    kill_switch_armed: bool = False,
    kill_switch_reason: str = "",
    heartbeat: HeartbeatState | None = None,
    reconnect: ReconnectState | None = None,
    reconciliation: ReconciliationStatus | None = None,
    data_feed_status: DataFeedStatus | None = None,
) -> tuple[Alert, ...]:
    alerts: list[Alert] = []

    if kill_switch_armed:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.KILL_SWITCH,
                message="Kill switch is armed",
                detail={"reason": kill_switch_reason},
            )
        )

    for decision in risk_decisions:
        if not decision.approved:
            alerts.append(
                Alert(
                    severity=AlertSeverity.CRITICAL,
                    category=AlertCategory.RISK_VIOLATION,
                    message="Risk engine rejected a signal",
                    detail={"violations": ", ".join(decision.violations)},
                )
            )

    failed = [o for o in orders if o.execution_state in _FAILED_STATES]
    if failed:
        alerts.append(
            Alert(
                severity=AlertSeverity.WARNING,
                category=AlertCategory.OMS_FAILURE,
                message=f"{len(failed)} order(s) failed or were rejected",
                detail={"order_ids": ", ".join(str(o.oms_order_id) for o in failed[:5])},
            )
        )
    if oms_metrics is not None and oms_metrics.broker_uptime_ratio < 1.0:
        alerts.append(
            Alert(
                severity=AlertSeverity.WARNING,
                category=AlertCategory.BROKER_DISCONNECT,
                message="Broker uptime degraded",
                detail={"uptime_ratio": str(oms_metrics.broker_uptime_ratio)},
            )
        )

    if heartbeat is not None and not heartbeat.is_healthy:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.BROKER_DISCONNECT,
                message="Market-data heartbeat lost",
                detail={"delay_seconds": str(heartbeat.delay_seconds)},
            )
        )

    if reconnect is not None and reconnect.is_reconnecting:
        alerts.append(
            Alert(
                severity=AlertSeverity.WARNING,
                category=AlertCategory.RECONNECT_FAILURE,
                message="Live feed is reconnecting",
                detail={"attempts": str(reconnect.attempts)},
            )
        )

    if reconciliation is not None and not reconciliation.reconciled:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.RECONCILIATION_MISMATCH,
                message="OMS reconciliation mismatch",
                detail={
                    "missing_orders": str(reconciliation.missing_orders),
                    "status_drift": str(reconciliation.status_drift),
                    "position_drift": str(reconciliation.position_drift),
                },
            )
        )

    # A single failed tick is normal transient noise (a slow API call, a brief
    # network blip); three in a row means the feed is actually down (e.g. an
    # expired Kite access token) and every strategy is blind until it's fixed.
    if data_feed_status is not None and data_feed_status.consecutive_failures >= 3:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.DATA_FEED_FAILURE,
                message="Live data feed is failing — strategies cannot see the market",
                detail={
                    "consecutive_failures": str(data_feed_status.consecutive_failures),
                    "last_error": data_feed_status.last_error,
                },
            )
        )

    if data_feed_status is not None and data_feed_status.orphaned_symbols:
        alerts.append(
            Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.ORPHANED_POSITION,
                message=(
                    "Open position(s) with no active strategy — nothing will ever "
                    "exit these on its own"
                ),
                detail={"symbols": ", ".join(data_feed_status.orphaned_symbols)},
            )
        )

    return tuple(alerts)

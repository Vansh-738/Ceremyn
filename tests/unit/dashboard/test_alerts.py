from ceremyn.dashboard.alerts import derive_alerts
from ceremyn.dashboard.models import (
    AlertCategory,
    AlertSeverity,
    DataFeedStatus,
    ReconciliationStatus,
)
from ceremyn.live.heartbeat import HeartbeatState
from ceremyn.live.reconnect import ReconnectState
from ceremyn.oms.orders import OMSExecutionState
from tests.unit.dashboard.conftest import (
    NOW,
    make_oms_metrics,
    make_oms_order,
    make_risk_decision,
)


def categories(alerts: tuple) -> set:  # type: ignore[type-arg]
    return {a.category for a in alerts}


def test_no_alerts_when_healthy() -> None:
    assert derive_alerts() == ()


def test_kill_switch_alert() -> None:
    alerts = derive_alerts(kill_switch_armed=True, kill_switch_reason="loss limit")
    assert AlertCategory.KILL_SWITCH in categories(alerts)
    assert alerts[0].severity is AlertSeverity.CRITICAL


def test_risk_violation_alert() -> None:
    alerts = derive_alerts(risk_decisions=(make_risk_decision(approved=False),))
    assert AlertCategory.RISK_VIOLATION in categories(alerts)


def test_oms_failure_alert() -> None:
    orders = (make_oms_order(state=OMSExecutionState.FAILED, last_error="broker down"),)
    alerts = derive_alerts(orders=orders)
    assert AlertCategory.OMS_FAILURE in categories(alerts)


def test_broker_uptime_alert() -> None:
    metrics = make_oms_metrics()
    metrics.record_broker_health(success=False)
    alerts = derive_alerts(oms_metrics=metrics.snapshot(NOW))
    assert AlertCategory.BROKER_DISCONNECT in categories(alerts)


def test_heartbeat_lost_alert() -> None:
    alerts = derive_alerts(
        heartbeat=HeartbeatState(is_healthy=False, last_seen_at=NOW, delay_seconds=9.0)
    )
    assert AlertCategory.BROKER_DISCONNECT in categories(alerts)


def test_reconnect_alert() -> None:
    alerts = derive_alerts(reconnect=ReconnectState(attempts=3, is_reconnecting=True))
    assert AlertCategory.RECONNECT_FAILURE in categories(alerts)


def test_reconciliation_mismatch_alert() -> None:
    alerts = derive_alerts(reconciliation=ReconciliationStatus(reconciled=False, position_drift=1))
    assert AlertCategory.RECONCILIATION_MISMATCH in categories(alerts)


def test_data_feed_failure_alert_after_three_consecutive_failures() -> None:
    alerts = derive_alerts(
        data_feed_status=DataFeedStatus(consecutive_failures=3, last_error="token expired")
    )
    assert AlertCategory.DATA_FEED_FAILURE in categories(alerts)
    assert alerts[0].severity is AlertSeverity.CRITICAL
    assert alerts[0].detail["last_error"] == "token expired"


def test_no_data_feed_alert_for_a_single_transient_failure() -> None:
    alerts = derive_alerts(data_feed_status=DataFeedStatus(consecutive_failures=1))
    assert AlertCategory.DATA_FEED_FAILURE not in categories(alerts)


def test_orphaned_position_alert() -> None:
    alerts = derive_alerts(data_feed_status=DataFeedStatus(orphaned_symbols=("NIFTY2672124600CE",)))
    assert AlertCategory.ORPHANED_POSITION in categories(alerts)
    orphaned = next(a for a in alerts if a.category is AlertCategory.ORPHANED_POSITION)
    assert orphaned.severity is AlertSeverity.CRITICAL
    assert "NIFTY2672124600CE" in orphaned.detail["symbols"]


def test_no_orphaned_position_alert_when_none_found() -> None:
    alerts = derive_alerts(data_feed_status=DataFeedStatus())
    assert AlertCategory.ORPHANED_POSITION not in categories(alerts)


def test_all_alert_types_together() -> None:
    metrics = make_oms_metrics()
    metrics.record_broker_health(success=False)
    alerts = derive_alerts(
        risk_decisions=(make_risk_decision(approved=False),),
        orders=(make_oms_order(state=OMSExecutionState.REJECTED),),
        oms_metrics=metrics.snapshot(NOW),
        kill_switch_armed=True,
        heartbeat=HeartbeatState(is_healthy=False, last_seen_at=NOW, delay_seconds=9.0),
        reconnect=ReconnectState(attempts=2, is_reconnecting=True),
        reconciliation=ReconciliationStatus(reconciled=False, position_drift=1),
    )
    assert {
        AlertCategory.KILL_SWITCH,
        AlertCategory.RISK_VIOLATION,
        AlertCategory.OMS_FAILURE,
        AlertCategory.BROKER_DISCONNECT,
        AlertCategory.RECONNECT_FAILURE,
        AlertCategory.RECONCILIATION_MISMATCH,
    } <= categories(alerts)

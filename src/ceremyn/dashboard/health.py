"""System-health view assembly from live/OMS observability state."""

from ceremyn.dashboard.models import ComponentHealth, DataFeedStatus, HealthView
from ceremyn.live.heartbeat import HeartbeatState
from ceremyn.live.metrics import LiveMetricsSnapshot
from ceremyn.live.reconnect import ReconnectState
from ceremyn.oms.metrics import OMSMetricsSnapshot

# Matches the alert threshold in `alerts.py`: one failed tick is normal transient
# noise, three in a row means the feed is actually down.
_FEED_FAILURE_THRESHOLD = 3


def build_health(
    *,
    heartbeat: HeartbeatState | None = None,
    reconnect: ReconnectState | None = None,
    live_metrics: LiveMetricsSnapshot | None = None,
    oms_metrics: OMSMetricsSnapshot | None = None,
    components_present: dict[str, bool] | None = None,
    data_feed_status: DataFeedStatus | None = None,
) -> HealthView:
    heartbeat_healthy = heartbeat.is_healthy if heartbeat is not None else True
    broker_uptime = oms_metrics.broker_uptime_ratio if oms_metrics is not None else 1.0

    components: list[ComponentHealth] = []
    for name, present in (components_present or {}).items():
        components.append(
            ComponentHealth(
                name=name,
                healthy=present,
                detail="" if present else "source not connected",
            )
        )
    # Presence above only means a source is wired, not that it's actually working
    # (see `data_feed`) -- this is the one component this dashboard can currently
    # tell is really failing, not just absent.
    if data_feed_status is not None:
        failing = data_feed_status.consecutive_failures >= _FEED_FAILURE_THRESHOLD
        components.append(
            ComponentHealth(
                name="data_feed",
                healthy=not failing,
                detail=data_feed_status.last_error if failing else "",
            )
        )
        components.append(
            ComponentHealth(
                name="position_ownership",
                healthy=not data_feed_status.orphaned_symbols,
                detail=(
                    ", ".join(data_feed_status.orphaned_symbols)
                    if data_feed_status.orphaned_symbols
                    else ""
                ),
            )
        )

    return HealthView(
        heartbeat_healthy=heartbeat_healthy,
        heartbeat_delay_seconds=heartbeat.delay_seconds if heartbeat is not None else 0.0,
        reconnect_attempts=reconnect.attempts if reconnect is not None else 0,
        is_reconnecting=reconnect.is_reconnecting if reconnect is not None else False,
        broker_uptime_ratio=broker_uptime,
        messages_per_second=(live_metrics.messages_per_second if live_metrics is not None else 0.0),
        components=tuple(components),
    )

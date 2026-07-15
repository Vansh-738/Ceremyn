"""System-health view assembly from live/OMS observability state."""

from alphaquant.dashboard.models import ComponentHealth, HealthView
from alphaquant.live.heartbeat import HeartbeatState
from alphaquant.live.metrics import LiveMetricsSnapshot
from alphaquant.live.reconnect import ReconnectState
from alphaquant.oms.metrics import OMSMetricsSnapshot


def build_health(
    *,
    heartbeat: HeartbeatState | None = None,
    reconnect: ReconnectState | None = None,
    live_metrics: LiveMetricsSnapshot | None = None,
    oms_metrics: OMSMetricsSnapshot | None = None,
    components_present: dict[str, bool] | None = None,
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

    return HealthView(
        heartbeat_healthy=heartbeat_healthy,
        heartbeat_delay_seconds=heartbeat.delay_seconds if heartbeat is not None else 0.0,
        reconnect_attempts=reconnect.attempts if reconnect is not None else 0,
        is_reconnecting=reconnect.is_reconnecting if reconnect is not None else False,
        broker_uptime_ratio=broker_uptime,
        messages_per_second=(live_metrics.messages_per_second if live_metrics is not None else 0.0),
        components=tuple(components),
    )

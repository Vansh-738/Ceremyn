"""WebSocket framing: live-event translation and snapshot change-detection.

Two push paths feed the WebSocket, neither of which polls:
- ``EventBridge`` subscribes the core ``EventBus`` and turns live engine events into
  immediate ``event`` frames.
- ``SnapshotDiffer`` samples the read-model and emits a ``snapshot`` frame for a channel
  only when that channel's content hash changed.
"""

import hashlib
import json
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from ceremyn.core.events import EventBus
from ceremyn.dashboard.models import Channel, WSFrame
from ceremyn.live.events import (
    HeartbeatLost,
    HeartbeatRecovered,
    MarketClose,
    MarketOpen,
    ReconnectFailed,
    ReconnectStarted,
    ReconnectSucceeded,
)

if TYPE_CHECKING:
    from ceremyn.dashboard.backend import DashboardService

logger = structlog.get_logger(__name__)


class FrameSink(Protocol):
    """Anything that can broadcast a WebSocket frame (the ConnectionManager)."""

    async def broadcast(self, frame: WSFrame) -> None: ...


# Live event class -> (channel it affects). Only alert/health/market-relevant events are
# pushed as event frames; high-frequency tick/snapshot events are covered by the differ.
_EVENT_CHANNEL: dict[type, Channel] = {
    HeartbeatLost: Channel.HEALTH,
    HeartbeatRecovered: Channel.HEALTH,
    ReconnectStarted: Channel.HEALTH,
    ReconnectFailed: Channel.HEALTH,
    ReconnectSucceeded: Channel.HEALTH,
    MarketOpen: Channel.LIVE,
    MarketClose: Channel.LIVE,
}


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class SnapshotDiffer:
    """Emits snapshot frames only for channels whose content changed."""

    def __init__(self) -> None:
        self._hashes: dict[str, str] = {}

    def _payload_or_none(
        self, service: "DashboardService", channel: Channel
    ) -> dict[str, Any] | None:
        # One channel's view can do real I/O (e.g. `oms` triggers a broker reconciliation
        # round-trip) -- a transient failure there must never take down every other
        # channel's updates, and must never kill the broadcaster loop that calls this
        # every tick (an uncaught exception here would silently freeze the whole
        # dashboard until the process is restarted).
        try:
            return service.channel_payload(channel)
        except Exception:
            logger.error("dashboard_channel_payload_failed", channel=channel.value, exc_info=True)
            return None

    def snapshot_all(
        self, service: "DashboardService", channels: tuple[Channel, ...]
    ) -> list[WSFrame]:
        """Full snapshot of every channel (used on connect); primes the hashes."""
        frames: list[WSFrame] = []
        for channel in channels:
            payload = self._payload_or_none(service, channel)
            if payload is None:
                continue
            self._hashes[channel.value] = _digest(payload)
            frames.append(WSFrame(kind="snapshot", channel=channel.value, payload=payload))
        return frames

    def changed(self, service: "DashboardService", channels: tuple[Channel, ...]) -> list[WSFrame]:
        """Snapshot frames for only the channels whose content changed since last call."""
        frames: list[WSFrame] = []
        for channel in channels:
            payload = self._payload_or_none(service, channel)
            if payload is None:
                continue
            digest = _digest(payload)
            if self._hashes.get(channel.value) != digest:
                self._hashes[channel.value] = digest
                frames.append(WSFrame(kind="snapshot", channel=channel.value, payload=payload))
        return frames


class EventBridge:
    """Translates core-bus live events into WebSocket event frames."""

    def frame_for(self, event: object) -> WSFrame | None:
        channel = _EVENT_CHANNEL.get(type(event))
        if channel is None:
            return None
        payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else {}
        return WSFrame(
            kind="event",
            channel=channel.value,
            payload={"event": type(event).__name__, **payload},
        )

    def register(self, bus: EventBus, sink: FrameSink) -> None:
        """Subscribe every mapped live event type; forward translated frames to `sink`."""
        for event_type in _EVENT_CHANNEL:

            async def handler(event: object, _sink: FrameSink = sink) -> None:
                frame = self.frame_for(event)
                if frame is not None:
                    await _sink.broadcast(frame)

            bus.subscribe(event_type, handler)

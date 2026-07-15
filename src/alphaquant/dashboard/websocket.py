"""WebSocket connection management and the snapshot broadcaster.

The ConnectionManager tracks connections and their channel subscriptions, and fans a
frame out only to the connections subscribed to that frame's channel. It is transport
agnostic: it talks to a minimal ``WebSocketLike`` protocol, so tests inject a fake and
FastAPI's ``WebSocket`` satisfies it directly.
"""

from typing import Any, Protocol

from alphaquant.dashboard.backend import DashboardService
from alphaquant.dashboard.events import SnapshotDiffer
from alphaquant.dashboard.models import Channel, WSFrame

ALL_CHANNELS: tuple[Channel, ...] = tuple(Channel)


class WebSocketLike(Protocol):
    async def send_json(self, data: Any) -> None: ...


class Connection:
    def __init__(self, socket: WebSocketLike, channels: tuple[Channel, ...]) -> None:
        self.socket = socket
        self.channels: set[Channel] = set(channels)
        self.dropped = 0

    async def send(self, frame: WSFrame) -> bool:
        """Send a frame; on transport failure mark dropped and report False."""
        try:
            await self.socket.send_json(frame.model_dump(mode="json"))
            return True
        except Exception:  # a slow/broken client must not break the broadcast
            self.dropped += 1
            return False


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[Connection] = []

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def add(self, socket: WebSocketLike, channels: tuple[Channel, ...]) -> Connection:
        connection = Connection(socket, channels)
        self._connections.append(connection)
        return connection

    def remove(self, connection: Connection) -> None:
        if connection in self._connections:
            self._connections.remove(connection)

    def subscribe(self, connection: Connection, channels: tuple[Channel, ...]) -> None:
        connection.channels.update(channels)

    def unsubscribe(self, connection: Connection, channels: tuple[Channel, ...]) -> None:
        connection.channels.difference_update(channels)

    async def broadcast(self, frame: WSFrame) -> int:
        """Send `frame` to every connection subscribed to its channel; return recipients."""
        sent = 0
        for connection in list(self._connections):
            if Channel(frame.channel) in connection.channels and await connection.send(frame):
                sent += 1
        return sent


async def broadcast_changes(
    service: DashboardService,
    differ: SnapshotDiffer,
    manager: ConnectionManager,
    *,
    channels: tuple[Channel, ...] = ALL_CHANNELS,
) -> int:
    """One broadcaster iteration: push a frame per changed channel. Returns frames sent."""
    sent = 0
    for frame in differ.changed(service, channels):
        sent += await manager.broadcast(frame)
    return sent

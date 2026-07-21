from typing import Any

from ceremyn.dashboard.backend import DashboardService
from ceremyn.dashboard.events import SnapshotDiffer
from ceremyn.dashboard.models import Channel, WSFrame
from ceremyn.dashboard.websocket import ConnectionManager, broadcast_changes


class FakeSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[Any] = []
        self.fail = fail

    async def send_json(self, data: Any) -> None:
        if self.fail:
            raise RuntimeError("client gone")
        self.sent.append(data)


def frame(channel: Channel = Channel.OVERVIEW) -> WSFrame:
    return WSFrame(kind="snapshot", channel=channel.value, payload={"x": 1})


class TestConnectionManager:
    async def test_broadcast_to_subscribed_only(self) -> None:
        manager = ConnectionManager()
        overview_sock = FakeSocket()
        oms_sock = FakeSocket()
        manager.add(overview_sock, (Channel.OVERVIEW,))
        manager.add(oms_sock, (Channel.OMS,))
        sent = await manager.broadcast(frame(Channel.OVERVIEW))
        assert sent == 1
        assert len(overview_sock.sent) == 1
        assert oms_sock.sent == []

    async def test_subscribe_and_unsubscribe(self) -> None:
        manager = ConnectionManager()
        sock = FakeSocket()
        conn = manager.add(sock, ())
        manager.subscribe(conn, (Channel.OMS,))
        assert await manager.broadcast(frame(Channel.OMS)) == 1
        manager.unsubscribe(conn, (Channel.OMS,))
        assert await manager.broadcast(frame(Channel.OMS)) == 0

    async def test_failed_send_counts_as_dropped(self) -> None:
        manager = ConnectionManager()
        conn = manager.add(FakeSocket(fail=True), (Channel.OVERVIEW,))
        assert await manager.broadcast(frame()) == 0
        assert conn.dropped == 1

    async def test_remove(self) -> None:
        manager = ConnectionManager()
        conn = manager.add(FakeSocket(), (Channel.OVERVIEW,))
        assert manager.connection_count == 1
        manager.remove(conn)
        assert manager.connection_count == 0


class TestBroadcastChanges:
    async def test_pushes_changed_then_nothing(self, service: DashboardService) -> None:
        manager = ConnectionManager()
        sock = FakeSocket()
        manager.add(sock, (Channel.OVERVIEW,))
        differ = SnapshotDiffer()
        first = await broadcast_changes(service, differ, manager, channels=(Channel.OVERVIEW,))
        assert first == 1
        second = await broadcast_changes(service, differ, manager, channels=(Channel.OVERVIEW,))
        assert second == 0  # unchanged -> no frame

from datetime import UTC, datetime

from alphaquant.core.events import EventBus
from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.dashboard.events import EventBridge, SnapshotDiffer
from alphaquant.dashboard.models import Channel, WSFrame
from alphaquant.live.events import HeartbeatLost, TickReceived

NOW = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)
CHANNELS = (Channel.OVERVIEW, Channel.HEALTH)


class TestSnapshotDiffer:
    def test_snapshot_all_returns_every_channel(self, service: DashboardService) -> None:
        differ = SnapshotDiffer()
        frames = differ.snapshot_all(service, CHANNELS)
        assert {f.channel for f in frames} == {c.value for c in CHANNELS}
        assert all(f.kind == "snapshot" for f in frames)

    def test_changed_empty_when_state_stable(self, service: DashboardService) -> None:
        differ = SnapshotDiffer()
        differ.snapshot_all(service, CHANNELS)
        # Nothing changed since the priming snapshot.
        assert differ.changed(service, CHANNELS) == []

    def test_changed_detects_new_state(self) -> None:
        differ = SnapshotDiffer()
        empty = DashboardService(DashboardSources())
        differ.snapshot_all(empty, (Channel.OVERVIEW,))
        # A service whose overview differs yields a frame.
        from tests.unit.dashboard.conftest import FakeOMS, make_oms_order

        changed_service = DashboardService(
            DashboardSources(oms=FakeOMS(orders=(make_oms_order(),)))
        )
        frames = differ.changed(changed_service, (Channel.OVERVIEW,))
        assert len(frames) == 1
        assert frames[0].channel == Channel.OVERVIEW.value

    def test_a_channel_that_raises_is_skipped_without_crashing_others(self) -> None:
        """Regression: one channel's view doing real I/O (e.g. `oms` triggering a
        broker reconciliation round-trip) must never take down the whole broadcaster
        loop or block every other channel's updates."""

        class ExplodingOMS:
            def orders(self):  # type: ignore[no-untyped-def]
                return ()

            def oms_metrics(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("broker unreachable")

            def kill_switch(self):  # type: ignore[no-untyped-def]
                return None

            def portfolio_snapshot(self):  # type: ignore[no-untyped-def]
                return None

            def reconciliation(self):  # type: ignore[no-untyped-def]
                return None

            def equity_curve(self):  # type: ignore[no-untyped-def]
                return ()

        differ = SnapshotDiffer()
        service = DashboardService(DashboardSources(oms=ExplodingOMS()))

        # Must not raise, and must not emit a frame for the channel that failed.
        # `research` has no dependency on `oms` at all, unlike `overview` (which also
        # reads `oms_metrics()` and would legitimately fail too).
        frames = differ.changed(service, (Channel.OMS, Channel.RESEARCH))
        assert all(f.channel != Channel.OMS.value for f in frames)
        # The unrelated, healthy channel still comes through.
        assert any(f.channel == Channel.RESEARCH.value for f in frames)


class TestEventBridge:
    def test_frame_for_mapped_event(self) -> None:
        frame = EventBridge().frame_for(HeartbeatLost(occurred_at=NOW, last_seen_at=NOW))
        assert frame is not None
        assert frame.kind == "event"
        assert frame.channel == Channel.HEALTH.value
        assert frame.payload["event"] == "HeartbeatLost"

    def test_frame_for_unmapped_event_is_none(self) -> None:
        # TickReceived is high-frequency and intentionally not pushed as an event frame.
        tick = TickReceived.model_construct()
        assert EventBridge().frame_for(tick) is None

    async def test_register_forwards_to_sink(self) -> None:
        bus = EventBus()
        received: list[WSFrame] = []

        class Sink:
            async def broadcast(self, frame: WSFrame) -> None:
                received.append(frame)

        EventBridge().register(bus, Sink())
        await bus.publish(HeartbeatLost(occurred_at=NOW, last_seen_at=NOW))
        assert len(received) == 1
        assert received[0].channel == Channel.HEALTH.value

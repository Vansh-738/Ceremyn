from collections.abc import Sequence
from datetime import timedelta

import pytest

from ceremyn.core.events import EventBus
from ceremyn.live import HeartbeatMonitor, LiveMarketDataEngine, ReconnectManager
from ceremyn.live.events import (
    HeartbeatLost,
    HeartbeatRecovered,
    MarketOpen,
    ReconnectStarted,
    ReconnectSucceeded,
    SnapshotBuilt,
    TickReceived,
)
from tests.unit.live.conftest import BASE_TS, tick_payload


class FakeClient:
    def __init__(self) -> None:
        self.subscribed: list[list[int]] = []
        self.unsubscribed: list[list[int]] = []
        self.modes: list[tuple[str, list[int]]] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.subscribed.append(list(instrument_tokens))

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.unsubscribed.append(list(instrument_tokens))

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.modes.append((mode, list(instrument_tokens)))


@pytest.mark.asyncio
async def test_engine_builds_snapshot_publishes_events_and_bridges_to_paper(
    underlyings, contracts, analytics
) -> None:
    client = FakeClient()
    bus = EventBus()
    received: list[object] = []
    for event_type in (TickReceived, SnapshotBuilt, MarketOpen):
        bus.subscribe(event_type, received.append)
    engine = LiveMarketDataEngine(
        underlyings=underlyings,
        contracts=contracts,
        analytics=analytics,
        client=client,
        event_bus=bus,
    )
    engine.start()

    assert (
        await engine.on_raw_tick(
            tick_payload(256265, last_price="24010", bid="24009", ask="24011"),
            received_at=BASE_TS,
        )
        is None
    )
    assert (
        await engine.on_raw_tick(
            tick_payload(101, last_price="150", bid="149.5", ask="150.5"),
            received_at=BASE_TS,
        )
        is None
    )
    snapshot = await engine.on_raw_tick(
        tick_payload(
            102,
            last_price="145",
            bid="144.5",
            ask="145.5",
            timestamp=BASE_TS + timedelta(seconds=1),
        ),
        received_at=BASE_TS + timedelta(seconds=1),
    )

    assert snapshot is not None
    assert engine.latest_snapshot("NIFTY") == snapshot
    paper_tick = engine.as_paper_tick(snapshot)
    assert paper_tick.chain == snapshot.option_chain
    assert any(isinstance(event, SnapshotBuilt) for event in received)
    assert any(isinstance(event, MarketOpen) for event in received)
    assert client.subscribed


@pytest.mark.asyncio
async def test_engine_heartbeat_and_reconnect_events(underlyings, contracts, analytics) -> None:
    bus = EventBus()
    seen: list[object] = []
    for event_type in (HeartbeatLost, HeartbeatRecovered, ReconnectStarted, ReconnectSucceeded):
        bus.subscribe(event_type, seen.append)
    engine = LiveMarketDataEngine(
        underlyings=underlyings,
        contracts=contracts,
        analytics=analytics,
        event_bus=bus,
        heartbeat=HeartbeatMonitor(timeout_seconds=1),
        reconnect=ReconnectManager(max_attempts=2, base_delay_seconds=0.1),
    )

    await engine.on_raw_tick(
        tick_payload(256265, last_price="24010", bid="24009", ask="24011"),
        received_at=BASE_TS,
    )
    await engine.check_heartbeat(now=BASE_TS + timedelta(seconds=2))
    await engine.on_reconnect_succeeded(when=BASE_TS + timedelta(seconds=3))

    assert any(isinstance(event, HeartbeatLost) for event in seen)
    assert any(isinstance(event, ReconnectStarted) for event in seen)
    assert any(isinstance(event, ReconnectSucceeded) for event in seen)
    assert any(isinstance(event, HeartbeatRecovered) for event in seen)

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from ceremyn.live.kite import KiteStreamingClient
from ceremyn.live.stream import AsyncTickStream


class FakeTicker:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.subscribed: list[list[int]] = []
        self.unsubscribed: list[list[int]] = []
        self.modes: list[tuple[str, list[int]]] = []
        self.on_ticks: Any = None
        self.on_connect: Any = None
        self.on_close: Any = None
        self.on_error: Any = None
        self.on_reconnect: Any = None
        self.on_noreconnect: Any = None

    def connect(self, threaded=False) -> None:
        self.connected = threaded

    def close(self) -> None:
        self.closed = True

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.subscribed.append(list(instrument_tokens))

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.unsubscribed.append(list(instrument_tokens))

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self.modes.append((mode, list(instrument_tokens)))


class FakeLiveEngine:
    def __init__(self) -> None:
        self.reconnect_succeeded_count = 0
        self.reconnect_failed_reasons: list[str] = []

    async def on_reconnect_succeeded(self, *, when: datetime | None = None) -> None:
        self.reconnect_succeeded_count += 1

    async def on_reconnect_failed(self, reason: str, *, when: datetime | None = None) -> None:
        self.reconnect_failed_reasons.append(reason)


@pytest.mark.asyncio
async def test_kite_streaming_client_delegates_and_binds_stream() -> None:
    ticker = FakeTicker()
    client = KiteStreamingClient(ticker)
    stream = AsyncTickStream()
    engine = FakeLiveEngine()
    client.bind_stream(stream, engine=engine)  # type: ignore[arg-type]
    client.connect()
    client.subscribe([1, 2])
    client.set_mode("full", [1, 2])
    client.unsubscribe([2])
    client.close()

    ticker.on_ticks(
        None,
        [
            {
                "instrument_token": 1,
                "last_price": 100.0,
                "exchange_timestamp": datetime(2026, 7, 14, 4, 20, tzinfo=UTC),
            }
        ],
    )
    batch = await asyncio.wait_for(anext(stream.batches()), timeout=1)

    assert ticker.connected is True
    assert ticker.closed is True
    assert ticker.subscribed == [[1, 2]]
    assert ticker.unsubscribed == [[2]]
    assert ticker.modes == [("full", [1, 2])]
    assert batch.ticks[0]["instrument_token"] == 1


@pytest.mark.asyncio
async def test_bind_stream_wires_reconnect_lifecycle_to_the_engine() -> None:
    ticker = FakeTicker()
    client = KiteStreamingClient(ticker)
    engine = FakeLiveEngine()
    client.bind_stream(AsyncTickStream(), engine=engine)  # type: ignore[arg-type]

    ticker.on_connect(None, {})
    await asyncio.sleep(0.01)  # let the threadsafe-scheduled task run to completion
    assert engine.reconnect_succeeded_count == 1

    ticker.on_noreconnect(None)
    await asyncio.sleep(0.01)
    assert engine.reconnect_failed_reasons == ["kite ticker exhausted its own reconnect attempts"]

    # Attempt-in-progress and transport noise are logged only, not routed to the
    # engine — check_heartbeat() (silence-based) is the single source of truth.
    ticker.on_close(None, 1006, "abnormal closure")
    ticker.on_error(None, 1006, "abnormal closure")
    ticker.on_reconnect(None, 1)
    await asyncio.sleep(0.01)
    assert engine.reconnect_succeeded_count == 1
    assert len(engine.reconnect_failed_reasons) == 1

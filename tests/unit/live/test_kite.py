import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from alphaquant.live.kite import KiteStreamingClient
from alphaquant.live.stream import AsyncTickStream


class FakeTicker:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.subscribed: list[list[int]] = []
        self.unsubscribed: list[list[int]] = []
        self.modes: list[tuple[str, list[int]]] = []
        self.on_ticks: Any = None

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


@pytest.mark.asyncio
async def test_kite_streaming_client_delegates_and_binds_stream() -> None:
    ticker = FakeTicker()
    client = KiteStreamingClient(ticker)
    stream = AsyncTickStream()
    client.bind_stream(stream)
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

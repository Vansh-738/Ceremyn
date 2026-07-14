"""Kite WebSocket adapter for the live engine."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from alphaquant.config import Settings
from alphaquant.core.timeutils import now_utc
from alphaquant.live.feed import StreamingClient
from alphaquant.live.stream import AsyncTickStream, StreamTickBatch


class KiteStreamingClient(StreamingClient):
    def __init__(self, ticker: Any) -> None:
        self._ticker = ticker

    @classmethod
    def from_settings(cls, settings: Settings, *, access_token: str) -> "KiteStreamingClient":
        from kiteconnect import KiteTicker

        return cls(KiteTicker(settings.kite.api_key, access_token, reconnect=True))

    def connect(self) -> None:
        self._ticker.connect(threaded=True)

    def close(self) -> None:
        self._ticker.close()

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self._ticker.subscribe(list(instrument_tokens))

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None:
        self._ticker.unsubscribe(list(instrument_tokens))

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        self._ticker.set_mode(mode, list(instrument_tokens))

    def bind_stream(self, stream: AsyncTickStream) -> None:
        import asyncio

        loop = asyncio.get_running_loop()

        def on_ticks(_: Any, ticks: list[dict[str, Any]]) -> None:
            received_at = now_utc()
            batch = StreamTickBatch(ticks=tuple(ticks), received_at=received_at)
            loop.call_soon_threadsafe(asyncio.create_task, stream.publish(batch))

        self._ticker.on_ticks = on_ticks


def tick_timestamp(payload: dict[str, Any], *, fallback: datetime) -> datetime:
    raw = (
        payload.get("exchange_timestamp")
        or payload.get("last_trade_time")
        or payload.get("timestamp")
    )
    return raw if isinstance(raw, datetime) else fallback

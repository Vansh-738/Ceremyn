"""Kite WebSocket adapter for the live engine."""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from alphaquant.config import Settings
from alphaquant.core.timeutils import now_utc
from alphaquant.live.feed import StreamingClient
from alphaquant.live.stream import AsyncTickStream, StreamTickBatch

if TYPE_CHECKING:
    from alphaquant.live.engine import LiveMarketDataEngine

logger = structlog.get_logger(__name__)


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

    def bind_stream(self, stream: AsyncTickStream, *, engine: "LiveMarketDataEngine") -> None:
        """Wire every `KiteTicker` lifecycle callback to the running event loop.

        `on_ticks` feeds the tick stream (unchanged). The rest drive the engine's own
        heartbeat/reconnect state machine directly from real socket events, rather than
        leaving it to be inferred later purely from tick silence: `on_connect` covers
        both the first connect and every successful reconnect (`restore_subscriptions`
        is a no-op on an empty plan, so this is harmless pre-first-connect too);
        `on_noreconnect` is the one genuinely terminal failure — the ticker's own
        internal reconnect attempts are exhausted. `on_close`/`on_error`/`on_reconnect`
        (an attempt in progress) are logged only: the engine's `check_heartbeat()`
        (silence-based, driven by the runtime orchestrator's maintenance loop) is the
        single source of truth for "is the feed actually stale," so Kite's own
        in-progress signal isn't turned into a second, possibly-inconsistent state
        machine.
        """
        import asyncio

        loop = asyncio.get_running_loop()

        def on_ticks(_: Any, ticks: list[dict[str, Any]]) -> None:
            received_at = now_utc()
            batch = StreamTickBatch(ticks=tuple(ticks), received_at=received_at)
            loop.call_soon_threadsafe(asyncio.create_task, stream.publish(batch))

        def on_connect(_: Any, __: Any) -> None:
            loop.call_soon_threadsafe(asyncio.create_task, engine.on_reconnect_succeeded())

        def on_noreconnect(_: Any) -> None:
            loop.call_soon_threadsafe(
                asyncio.create_task,
                engine.on_reconnect_failed("kite ticker exhausted its own reconnect attempts"),
            )

        def on_close(_: Any, code: int, reason: str) -> None:
            logger.warning("kite_ticker_closed", code=code, reason=reason)

        def on_error(_: Any, code: int, reason: str) -> None:
            logger.warning("kite_ticker_error", code=code, reason=reason)

        def on_reconnect(_: Any, attempts_count: int) -> None:
            logger.info("kite_ticker_reconnecting", attempt=attempts_count)

        self._ticker.on_ticks = on_ticks
        self._ticker.on_connect = on_connect
        self._ticker.on_noreconnect = on_noreconnect
        self._ticker.on_close = on_close
        self._ticker.on_error = on_error
        self._ticker.on_reconnect = on_reconnect


def tick_timestamp(payload: dict[str, Any], *, fallback: datetime) -> datetime:
    raw = (
        payload.get("exchange_timestamp")
        or payload.get("last_trade_time")
        or payload.get("timestamp")
    )
    return raw if isinstance(raw, datetime) else fallback

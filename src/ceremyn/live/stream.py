"""Async stream bridge for raw feed messages."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ceremyn.domain.market_data import _require_aware


@dataclass(frozen=True)
class StreamTickBatch:
    ticks: tuple[dict[str, Any], ...]
    received_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.received_at)


class AsyncTickStream:
    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[StreamTickBatch | None] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, batch: StreamTickBatch) -> None:
        await self._queue.put(batch)

    async def close(self) -> None:
        await self._queue.put(None)

    async def batches(self) -> AsyncIterator[StreamTickBatch]:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item

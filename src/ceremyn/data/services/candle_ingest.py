"""Generic OHLCV backfill: any `Instrument` (option, future, equity, ETF), via
Kite historical candles.

Asset-agnostic by construction -- `KiteProvider.historical_candles` and
`CandleRepository` only ever need a tradingsymbol/broker_token/timeframe, never
an asset-class-specific field, so one service covers every instrument type.
"""

from datetime import datetime

import structlog

from ceremyn.core.exceptions import DataError
from ceremyn.data.providers.kite import KiteProvider
from ceremyn.data.repositories.candles import CandleRepository
from ceremyn.domain import Instrument, TimeFrame

logger = structlog.get_logger(__name__)


class CandleIngestService:
    def __init__(self, provider: KiteProvider, repository: CandleRepository) -> None:
        self._provider = provider
        self._repository = repository

    async def ingest_range(
        self,
        instrument: Instrument,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
    ) -> int:
        """Backfill `instrument`'s OHLCV history for [start, end]; returns rows stored."""
        if instrument.broker_token is None:
            raise DataError(f"cannot fetch history for {instrument.tradingsymbol}: no broker_token")
        candles = await self._provider.historical_candles(
            instrument.broker_token, instrument.tradingsymbol, timeframe, start, end
        )
        stored = await self._repository.upsert_many(candles)
        logger.info(
            "candles_ingested",
            tradingsymbol=instrument.tradingsymbol,
            timeframe=timeframe.value,
            rows=stored,
        )
        return stored

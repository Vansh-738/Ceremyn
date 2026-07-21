"""Candle repository."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ceremyn.data.repositories.models import CandleRow
from ceremyn.domain import Candle, TimeFrame


class CandleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_many(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        values = [
            {
                "tradingsymbol": c.tradingsymbol,
                "timeframe": c.timeframe.value,
                "ts": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "open_interest": c.open_interest,
            }
            for c in candles
        ]
        stmt = insert(CandleRow).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_candles_symbol_tf_ts",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "open_interest": stmt.excluded.open_interest,
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def fetch(
        self, tradingsymbol: str, timeframe: TimeFrame, start: datetime, end: datetime
    ) -> list[Candle]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(CandleRow)
                .where(
                    CandleRow.tradingsymbol == tradingsymbol,
                    CandleRow.timeframe == timeframe.value,
                    CandleRow.ts >= start,
                    CandleRow.ts <= end,
                )
                .order_by(CandleRow.ts)
            )
            return [
                Candle(
                    tradingsymbol=row.tradingsymbol,
                    timeframe=TimeFrame(row.timeframe),
                    timestamp=row.ts,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    open_interest=row.open_interest,
                )
                for row in rows
            ]

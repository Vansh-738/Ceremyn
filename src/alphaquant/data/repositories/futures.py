"""Future-chain EOD repository (mirrors `chains.py::OptionChainEodRepository`)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.records import EodFutureRecord
from alphaquant.data.repositories.models import FutureChainEodRow

_EOD_KEY = ["trade_date", "underlying", "expiry"]


class FutureChainEodRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_many(self, records: list[EodFutureRecord]) -> int:
        if not records:
            return 0
        values = [record.model_dump() for record in records]
        stmt = insert(FutureChainEodRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=_EOD_KEY,
            set_={
                column: getattr(stmt.excluded, column)
                for column in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "settle",
                    "volume",
                    "open_interest",
                    "oi_change",
                    "underlying_close",
                )
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def fetch_chain(self, underlying: str, trade_date: date) -> list[EodFutureRecord]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(FutureChainEodRow)
                .where(
                    FutureChainEodRow.underlying == underlying,
                    FutureChainEodRow.trade_date == trade_date,
                )
                .order_by(FutureChainEodRow.expiry)
            )
            return [_eod_to_record(row) for row in rows]

    async def trade_dates(self, underlying: str) -> list[date]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(FutureChainEodRow.trade_date)
                .where(FutureChainEodRow.underlying == underlying)
                .distinct()
                .order_by(FutureChainEodRow.trade_date)
            )
            return list(result)


def _eod_to_record(row: FutureChainEodRow) -> EodFutureRecord:
    return EodFutureRecord(
        trade_date=row.trade_date,
        underlying=row.underlying,
        expiry=row.expiry,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        settle=row.settle,
        volume=row.volume,
        open_interest=row.open_interest,
        oi_change=row.oi_change,
        underlying_close=row.underlying_close,
    )

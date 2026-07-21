"""Option-chain repositories: EOD history and intraday snapshots."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.records import EodOptionRecord
from alphaquant.data.repositories.models import ChainSnapshotEntryRow, OptionChainEodRow
from alphaquant.domain import OptionChainSnapshot

_EOD_KEY = ["trade_date", "underlying", "expiry", "strike", "option_type"]


class OptionChainEodRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_many(self, records: list[EodOptionRecord]) -> int:
        if not records:
            return 0
        values = [record.model_dump() for record in records]
        stmt = insert(OptionChainEodRow).values(values)
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
                    "lot_size",
                )
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def fetch_chain(
        self, underlying: str, trade_date: date, expiry: date
    ) -> list[EodOptionRecord]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(OptionChainEodRow)
                .where(
                    OptionChainEodRow.underlying == underlying,
                    OptionChainEodRow.trade_date == trade_date,
                    OptionChainEodRow.expiry == expiry,
                )
                .order_by(OptionChainEodRow.strike, OptionChainEodRow.option_type)
            )
            return [_eod_to_record(row) for row in rows]

    async def trade_dates(self, underlying: str) -> list[date]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(OptionChainEodRow.trade_date)
                .where(OptionChainEodRow.underlying == underlying)
                .distinct()
                .order_by(OptionChainEodRow.trade_date)
            )
            return list(result)

    async def expiries_on(self, underlying: str, trade_date: date) -> list[date]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(OptionChainEodRow.expiry)
                .where(
                    OptionChainEodRow.underlying == underlying,
                    OptionChainEodRow.trade_date == trade_date,
                )
                .distinct()
                .order_by(OptionChainEodRow.expiry)
            )
            return list(result)


def _eod_to_record(row: OptionChainEodRow) -> EodOptionRecord:
    return EodOptionRecord(
        trade_date=row.trade_date,
        underlying=row.underlying,
        expiry=row.expiry,
        strike=row.strike,
        option_type=row.option_type,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        settle=row.settle,
        volume=row.volume,
        open_interest=row.open_interest,
        oi_change=row.oi_change,
        underlying_close=row.underlying_close,
        lot_size=row.lot_size,
    )


class ChainSnapshotRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, snapshot: OptionChainSnapshot) -> int:
        values = [
            {
                "captured_at": snapshot.timestamp,
                "underlying": snapshot.underlying,
                "expiry": snapshot.expiry,
                "strike": entry.contract.strike,
                "option_type": entry.contract.option_type.value,
                "spot": snapshot.spot,
                "last_price": entry.quote.last_price if entry.quote else None,
                "bid": entry.quote.bid if entry.quote else None,
                "ask": entry.quote.ask if entry.quote else None,
                "volume": entry.quote.volume if entry.quote else 0,
                "open_interest": entry.open_interest,
                "iv": entry.greeks.iv if entry.greeks else None,
            }
            for entry in snapshot.entries
        ]
        stmt = insert(ChainSnapshotEntryRow).values(values).on_conflict_do_nothing()
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

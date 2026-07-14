"""Instrument repository: option contracts and their broker tokens."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.repositories.models import InstrumentRow
from alphaquant.domain import Exchange, OptionContract, OptionType


def _to_domain(row: InstrumentRow) -> OptionContract:
    if (
        row.underlying is None
        or row.expiry is None
        or row.strike is None
        or row.option_type is None
    ):
        raise ValueError(f"instrument {row.tradingsymbol} is not an option contract")
    return OptionContract(
        tradingsymbol=row.tradingsymbol,
        exchange=Exchange(row.exchange),
        tick_size=row.tick_size,
        broker_token=row.broker_token,
        underlying=row.underlying,
        expiry=row.expiry,
        strike=Decimal(row.strike),
        option_type=OptionType(row.option_type),
        lot_size=int(row.lot_size or 0),
    )


class InstrumentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_contracts(self, contracts: list[OptionContract]) -> int:
        if not contracts:
            return 0
        values = [
            {
                "tradingsymbol": c.tradingsymbol,
                "exchange": c.exchange.value,
                "underlying": c.underlying,
                "expiry": c.expiry,
                "strike": c.strike,
                "option_type": c.option_type.value,
                "lot_size": c.lot_size,
                "tick_size": c.tick_size,
                "broker_token": c.broker_token,
            }
            for c in contracts
        ]
        stmt = insert(InstrumentRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tradingsymbol"],
            set_={
                "lot_size": stmt.excluded.lot_size,
                "tick_size": stmt.excluded.tick_size,
                "broker_token": stmt.excluded.broker_token,
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def get(self, tradingsymbol: str) -> OptionContract | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(InstrumentRow).where(InstrumentRow.tradingsymbol == tradingsymbol)
            )
        return _to_domain(row) if row is not None else None

    async def list_contracts(self, underlying: str, expiry: date) -> list[OptionContract]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(InstrumentRow)
                .where(InstrumentRow.underlying == underlying, InstrumentRow.expiry == expiry)
                .order_by(InstrumentRow.strike, InstrumentRow.option_type)
            )
            return [_to_domain(row) for row in rows]

    async def expiries(self, underlying: str, on_or_after: date) -> list[date]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(InstrumentRow.expiry)
                .where(InstrumentRow.underlying == underlying, InstrumentRow.expiry >= on_or_after)
                .distinct()
                .order_by(InstrumentRow.expiry)
            )
            return [d for d in result if d is not None]

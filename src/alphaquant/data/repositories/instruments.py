"""Instrument repository: any `Instrument` subtype, keyed by tradingsymbol."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.repositories.models import InstrumentRow
from alphaquant.domain import (
    AssetClass,
    EquityInstrument,
    ETFInstrument,
    Exchange,
    FutureContract,
    Instrument,
    OptionContract,
    OptionType,
)


def _to_domain(row: InstrumentRow) -> Instrument:
    asset_class = AssetClass(row.asset_class)
    if asset_class is AssetClass.OPTION:
        if (
            row.underlying is None
            or row.expiry is None
            or row.strike is None
            or row.option_type is None
        ):
            raise ValueError(f"instrument {row.tradingsymbol} is missing option fields")
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
    if asset_class is AssetClass.FUTURES:
        if row.underlying is None or row.expiry is None:
            raise ValueError(f"instrument {row.tradingsymbol} is missing future fields")
        return FutureContract(
            tradingsymbol=row.tradingsymbol,
            exchange=Exchange(row.exchange),
            tick_size=row.tick_size,
            broker_token=row.broker_token,
            underlying=row.underlying,
            expiry=row.expiry,
            lot_size=int(row.lot_size or 1),
        )
    if row.underlying is None:
        raise ValueError(f"instrument {row.tradingsymbol} is missing underlying")
    cash_kwargs: dict[str, Any] = {
        "tradingsymbol": row.tradingsymbol,
        "exchange": Exchange(row.exchange),
        "tick_size": row.tick_size,
        "broker_token": row.broker_token,
        "underlying": row.underlying,
        "isin": row.isin,
        "lot_size": int(row.lot_size or 1),
    }
    if asset_class is AssetClass.EQUITY:
        return EquityInstrument(**cash_kwargs)
    if asset_class is AssetClass.ETF:
        return ETFInstrument(**cash_kwargs)
    raise ValueError(
        f"instrument {row.tradingsymbol} has unsupported asset_class {row.asset_class!r}"
    )


def _to_row_values(instrument: Instrument) -> dict[str, Any]:
    values: dict[str, Any] = {
        "tradingsymbol": instrument.tradingsymbol,
        "exchange": instrument.exchange.value,
        "asset_class": instrument.asset_class.value,
        "underlying": instrument.underlying,
        "expiry": instrument.expiry,
        "lot_size": instrument.lot_size,
        "tick_size": instrument.tick_size,
        "broker_token": instrument.broker_token,
        "strike": None,
        "option_type": None,
        "isin": None,
    }
    if isinstance(instrument, OptionContract):
        values["strike"] = instrument.strike
        values["option_type"] = instrument.option_type.value
    elif isinstance(instrument, EquityInstrument | ETFInstrument):
        values["isin"] = instrument.isin
    return values


class InstrumentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_contracts(self, contracts: Sequence[Instrument]) -> int:
        """Store or update any mix of `Instrument` subtypes (options, futures,
        equities, ETFs), keyed by tradingsymbol."""
        if not contracts:
            return 0
        values = [_to_row_values(instrument) for instrument in contracts]
        stmt = insert(InstrumentRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tradingsymbol"],
            set_={
                "asset_class": stmt.excluded.asset_class,
                "lot_size": stmt.excluded.lot_size,
                "tick_size": stmt.excluded.tick_size,
                "broker_token": stmt.excluded.broker_token,
                "strike": stmt.excluded.strike,
                "option_type": stmt.excluded.option_type,
                "isin": stmt.excluded.isin,
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def get(self, tradingsymbol: str) -> Instrument | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(InstrumentRow).where(InstrumentRow.tradingsymbol == tradingsymbol)
            )
        return _to_domain(row) if row is not None else None

    async def list_contracts(self, underlying: str, expiry: date) -> list[Instrument]:
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

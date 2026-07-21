"""Corporate-action repository."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ceremyn.data.repositories.models import CorporateActionRow
from ceremyn.domain import CorporateAction, CorporateActionType

_KEY = ["tradingsymbol", "ex_date", "action_type"]


class CorporateActionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_many(self, actions: list[CorporateAction]) -> int:
        if not actions:
            return 0
        values = [
            {
                "tradingsymbol": action.tradingsymbol,
                "ex_date": action.ex_date,
                "action_type": action.action_type.value,
                "ratio": action.ratio,
                "dividend_amount": action.dividend_amount,
            }
            for action in actions
        ]
        stmt = insert(CorporateActionRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=_KEY,
            set_={
                "ratio": stmt.excluded.ratio,
                "dividend_amount": stmt.excluded.dividend_amount,
            },
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(stmt)
        return len(values)

    async def for_tradingsymbol(self, tradingsymbol: str) -> list[CorporateAction]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(CorporateActionRow)
                .where(CorporateActionRow.tradingsymbol == tradingsymbol)
                .order_by(CorporateActionRow.ex_date)
            )
            return [_to_domain(row) for row in rows]

    async def since(self, tradingsymbol: str, on_or_after: date) -> list[CorporateAction]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(CorporateActionRow)
                .where(
                    CorporateActionRow.tradingsymbol == tradingsymbol,
                    CorporateActionRow.ex_date >= on_or_after,
                )
                .order_by(CorporateActionRow.ex_date)
            )
            return [_to_domain(row) for row in rows]


def _to_domain(row: CorporateActionRow) -> CorporateAction:
    return CorporateAction(
        tradingsymbol=row.tradingsymbol,
        action_type=CorporateActionType(row.action_type),
        ex_date=row.ex_date,
        ratio=row.ratio,
        dividend_amount=row.dividend_amount,
    )

"""Async engine / session factory and the declarative base."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def create_engine_and_sessionmaker(
    url: str, *, echo: bool = False
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, echo=echo, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)

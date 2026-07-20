"""Bhavcopy backfill: download EOD F&O records for a date range and persist them.

Generic over the record type so the same day-iteration/calendar logic drives
both options (the default) and futures -- `parse` and `repository` must agree
on the record type; see `core.container.Container.future_bhavcopy_ingest` for
the futures wiring.
"""

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Generic, Protocol, TypeVar

import structlog

from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.exceptions import CalendarError, DataError
from alphaquant.data.providers.bhavcopy import BhavcopyClient, parse_bhavcopy

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class _EodRepository(Protocol[T]):
    async def upsert_many(self, records: list[T]) -> int: ...


class BhavcopyIngestService(Generic[T]):
    def __init__(
        self,
        client: BhavcopyClient,
        repository: _EodRepository[T],
        calendar: MarketCalendar,
        underlyings: tuple[str, ...],
        parse: Callable[[bytes, Iterable[str], date], list[T]] = parse_bhavcopy,  # type: ignore[assignment]
    ) -> None:
        self._client = client
        self._repository = repository
        self._calendar = calendar
        self._underlyings = underlyings
        self._parse = parse

    async def ingest_range(self, start: date, end: date) -> dict[date, int]:
        """Ingest every trading day in [start, end]; returns rows stored per day."""
        if end < start:
            raise ValueError("end date before start date")
        results: dict[date, int] = {}
        day = start
        while day <= end:
            if self._should_attempt(day):
                count = await self.ingest_day(day)
                if count is not None:
                    results[day] = count
            day += timedelta(days=1)
        return results

    async def ingest_day(self, day: date) -> int | None:
        """Ingest one day; returns rows stored, or None if no file exists."""
        try:
            payload = await self._client.download(day)
        except DataError as exc:
            logger.warning("bhavcopy_missing", trade_date=str(day), reason=str(exc))
            return None
        records = self._parse(payload, self._underlyings, day)
        stored = await self._repository.upsert_many(records)
        logger.info("bhavcopy_ingested", trade_date=str(day), rows=stored)
        return stored

    def _should_attempt(self, day: date) -> bool:
        try:
            return self._calendar.is_trading_day(day)
        except CalendarError:
            # Outside covered holiday years (e.g. deep backfills): weekends are
            # still certain non-trading days; try weekdays and let 404s skip.
            return day.weekday() < 5

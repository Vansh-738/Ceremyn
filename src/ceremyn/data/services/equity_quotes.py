"""Market-hours equity snapshots; read-only, independent of strategy execution."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

import structlog

from ceremyn.config.settings import EquityQuoteSettings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import now_utc, to_ist
from ceremyn.domain import Candle, Quote

logger = structlog.get_logger(__name__)
HistoryLoader = Callable[[date, date], Awaitable[dict[str, tuple[Candle, ...]]]]


class QuoteProvider(Protocol):
    async def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]: ...


class QuoteCache(Protocol):
    def set_quotes(self, quotes: tuple[Quote, ...]) -> None: ...


def rank_universe(
    history: dict[str, tuple[Candle, ...]], sessions: tuple[date, ...], limit: int
) -> tuple[str, ...]:
    """Require every completed session; rank raw close x volume, ties by symbol.

    Missing sessions cannot inflate an average by dropping zero-volume days.
    Raw bhavcopy prices are intentional: adjusted prices distort traded value.
    """
    ranked: list[tuple[Decimal, str]] = []
    for symbol, candles in history.items():
        by_day = {to_ist(c.timestamp).date(): c for c in candles}
        if not all(day in by_day for day in sessions):
            continue
        turnover = sum((by_day[day].close * by_day[day].volume for day in sessions), Decimal(0))
        if turnover > 0:
            ranked.append((turnover, symbol))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(symbol for _, symbol in ranked[:limit])


class EquityQuoteJob:
    def __init__(
        self,
        *,
        provider: QuoteProvider,
        cache: QuoteCache,
        history_loader: HistoryLoader,
        settings: EquityQuoteSettings,
        calendar: MarketCalendar,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._history_loader = history_loader
        self._settings = settings
        self._calendar = calendar
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._universe_date: date | None = None
        self.symbols: tuple[str, ...] = ()
        self.last_success_at: datetime | None = None
        self.last_error = ""
        self.consecutive_failures = 0

    async def start(self) -> None:
        if self._task is None and self._settings.enabled:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                self.consecutive_failures += 1
                self.last_error = str(exc)
                logger.error("equity_quote_snapshot_failed", exc_info=True)
            await asyncio.sleep(self._settings.interval_seconds)

    async def run_once(self) -> int:
        now = self._clock()
        if not self._calendar.is_market_open(now):
            return 0
        today = to_ist(now).date()
        if self._universe_date != today:
            sessions: list[date] = []
            day = today
            for _ in range(self._settings.turnover_sessions):
                day = self._calendar.previous_trading_day(day)
                sessions.append(day)
            history = await self._history_loader(sessions[-1], sessions[0])
            symbols = rank_universe(history, tuple(sessions), self._settings.universe_size)
            if not symbols:
                raise ValueError("no equities have complete trailing turnover history")
            self.symbols = symbols
            self._universe_date = today
        # History retrieval can cross the close; never start a quote call after it.
        if not self._calendar.is_market_open(self._clock()):
            return 0
        quotes = await self._provider.quotes([f"NSE:{symbol}" for symbol in self.symbols])
        received_at = self._clock()
        max_age = timedelta(seconds=self._settings.max_quote_age_seconds)
        accepted = tuple(
            quote
            for symbol in self.symbols
            if (quote := quotes.get(f"NSE:{symbol}")) is not None
            and quote.tradingsymbol == symbol
            and quote.last_price > 0
            and timedelta(0) <= received_at - quote.timestamp <= max_age
        )
        if not accepted:
            raise ValueError("no fresh equity quotes received")
        self._cache.set_quotes(accepted)
        self.last_success_at = received_at
        self.last_error = ""
        self.consecutive_failures = 0
        logger.info("equity_quote_snapshot", requested=len(self.symbols), accepted=len(accepted))
        return len(accepted)

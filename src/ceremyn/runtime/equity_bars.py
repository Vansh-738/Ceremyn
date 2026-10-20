"""Opt-in daily equity driver: evaluate yesterday's close during today's session."""

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta
from itertools import pairwise

import structlog

from ceremyn.config.settings import EquityBarSettings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import now_utc, to_ist
from ceremyn.data.services.equity_bars import bar_context
from ceremyn.data.services.equity_quotes import HistoryLoader, QuoteProvider
from ceremyn.domain import EquityInstrument, Exchange
from ceremyn.live.cache import LiveDataCache
from ceremyn.runtime.bars import BarStrategyDriver

logger = structlog.get_logger(__name__)


class EquityBarJob:
    def __init__(
        self,
        *,
        settings: EquityBarSettings,
        driver: BarStrategyDriver,
        history_loader: HistoryLoader,
        provider: QuoteProvider,
        cache: LiveDataCache,
        calendar: MarketCalendar,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self.settings = settings
        self.driver = driver
        self.history_loader = history_loader
        self.provider = provider
        self.cache = cache
        self.calendar = calendar
        self.clock = clock
        self._processed: set[tuple[str, datetime]] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.settings.enabled and self.settings.symbols and self._task is None:
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
            except Exception:
                logger.exception("equity_bar_cycle_failed")
            await asyncio.sleep(180)

    async def run_once(self) -> int:
        now = self.clock()
        if not self.calendar.is_market_open(now):
            return 0
        end = self.calendar.previous_trading_day(to_ist(now).date())
        if all(
            any(symbol == s and to_ist(at).date() == end for s, at in self._processed)
            for symbol in self.settings.symbols
        ):
            return 0
        history = await self.history_loader(end - timedelta(days=120), end)
        quotes = await self.provider.quotes([f"NSE:{s}" for s in self.settings.symbols])
        submitted = 0
        for symbol in self.settings.symbols:
            candles = history.get(symbol, ())
            quote = quotes.get(f"NSE:{symbol}")
            now = self.clock()
            if (
                not candles
                or to_ist(candles[-1].timestamp).date() != end
                or (symbol, candles[-1].timestamp) in self._processed
                or quote is None
                or quote.tradingsymbol != symbol
                or quote.last_price <= 0
                or not timedelta(0) <= now - quote.timestamp <= timedelta(minutes=5)
                or not self.calendar.is_market_open(now)
            ):
                continue
            # Until corporate-action records are supplied to this live data source,
            # a discontinuity blocks this symbol instead of becoming a false signal.
            if any(
                a.close <= 0 or abs(b.close / a.close - 1) > self.settings.max_daily_move
                for a, b in pairwise(candles)
            ):
                logger.warning("equity_bar_unresolved_price_discontinuity", symbol=symbol)
                continue
            if abs(quote.last_price / candles[-1].close - 1) > self.settings.max_entry_gap:
                continue
            self.cache.set_quote(quote)
            context = bar_context(
                EquityInstrument(tradingsymbol=symbol, underlying=symbol, exchange=Exchange.NSE),
                candles,
            )
            orders = self.driver.on_bar(context, now=now, reference_price=quote.last_price)
            submitted += len(orders)
            self._processed.add((symbol, candles[-1].timestamp))
        self._processed = {(s, at) for s, at in self._processed if to_ist(at).date() >= end}
        return submitted

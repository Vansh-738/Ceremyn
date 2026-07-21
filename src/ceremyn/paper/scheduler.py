"""Scheduler: gate paper-trading ticks to market hours.

The core is a deterministic, tickable driver — `advance(feed, now)` pulls the next tick
from the feed and dispatches it to the engine only when the market is open (reusing
`MarketCalendar.is_market_open`). Tests drive it by calling `advance` with controlled
timestamps; a thin optional APScheduler wrapper drives it on the wall clock in production.
"""

from collections.abc import Callable
from datetime import datetime

from ceremyn.core.calendar import MarketCalendar
from ceremyn.paper.events import MarketTick


class PaperScheduler:
    def __init__(
        self,
        calendar: MarketCalendar | None = None,
    ) -> None:
        self.calendar = calendar or MarketCalendar()
        self.ticks_processed = 0
        self.ticks_skipped = 0

    def is_open(self, now: datetime) -> bool:
        return self.calendar.is_market_open(now)

    def advance(
        self,
        tick: MarketTick,
        handler: Callable[[MarketTick], None],
        *,
        now: datetime | None = None,
    ) -> bool:
        """Dispatch `tick` to `handler` iff the market is open; return whether it ran."""
        moment = now or tick.as_of
        if not self.is_open(moment):
            self.ticks_skipped += 1
            return False
        handler(tick)
        self.ticks_processed += 1
        return True

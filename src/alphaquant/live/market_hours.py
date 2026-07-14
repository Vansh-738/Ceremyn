"""Market session state for the live engine."""

from datetime import datetime, time
from enum import StrEnum

from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.timeutils import to_ist


class MarketStatus(StrEnum):
    PRE_OPEN = "pre_open"
    OPEN = "open"
    CLOSED = "closed"
    HOLIDAY = "holiday"


class MarketHours:
    PRE_OPEN_START = time(9, 0)

    def __init__(self, calendar: MarketCalendar | None = None) -> None:
        self._calendar = calendar or MarketCalendar()

    def status(self, at: datetime) -> MarketStatus:
        local = to_ist(at)
        if not self._calendar.is_trading_day(local.date()):
            return MarketStatus.HOLIDAY
        if self.PRE_OPEN_START <= local.time() < self._calendar.OPEN:
            return MarketStatus.PRE_OPEN
        if self._calendar.OPEN <= local.time() <= self._calendar.CLOSE:
            return MarketStatus.OPEN
        return MarketStatus.CLOSED

    def is_session_active(self, at: datetime) -> bool:
        return self.status(at) in {MarketStatus.PRE_OPEN, MarketStatus.OPEN}

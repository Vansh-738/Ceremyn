"""Session-transition detection for the live engine."""

from datetime import datetime

from ceremyn.live.market_hours import MarketHours, MarketStatus


class MarketSessionScheduler:
    def __init__(self, market_hours: MarketHours | None = None) -> None:
        self._market_hours = market_hours or MarketHours()
        self._last_status: dict[str, MarketStatus] = {}

    def transition(self, underlying: str, at: datetime) -> tuple[MarketStatus | None, MarketStatus]:
        current = self._market_hours.status(at)
        previous = self._last_status.get(underlying)
        self._last_status[underlying] = current
        return previous, current

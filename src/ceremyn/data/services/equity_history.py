"""Free, credential-less equity OHLCV history via NSE cash-market bhavcopy.

One bhavcopy download per trading day covers every wanted symbol -- not one
download per symbol, which would mean hundreds of thousands of redundant
downloads at whole-market scale. `symbols=None` scans the entire real listed
equity universe found in each day's file rather than a hand-picked list.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

import structlog

from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.exceptions import DataError
from ceremyn.core.timeutils import IST
from ceremyn.data.providers.bhavcopy import EquityBhavcopyClient, parse_bhavcopy_equity
from ceremyn.data.records import EodEquityRecord
from ceremyn.domain import Candle, TimeFrame

logger = structlog.get_logger(__name__)

CLOSE_TIME = time(15, 30)


def _equity_candle(symbol: str, trade_date: date, record: EodEquityRecord) -> Candle | None:
    if record.close is None or record.close <= 0:
        return None
    return Candle(
        tradingsymbol=symbol,
        timeframe=TimeFrame.DAY,
        timestamp=datetime.combine(trade_date, CLOSE_TIME, tzinfo=IST),
        open=record.open or record.close,
        high=record.high or record.close,
        low=record.low or record.close,
        close=record.close,
        volume=record.volume,
    )


async def fetch_all_equity_candles(
    start: date, end: date, symbols: set[str] | None = None
) -> dict[str, tuple[Candle, ...]]:
    """One bhavcopy download per trading day; every wanted symbol's candle history
    is built from that same single pass."""
    calendar = MarketCalendar()
    client = EquityBhavcopyClient()
    accumulator: dict[str, list[Candle]] = defaultdict(list)
    day = start
    days_fetched = 0
    while day <= end:
        if calendar.is_trading_day(day):
            try:
                payload = await client.download(day)
            except DataError:
                pass
            else:
                days_fetched += 1
                for record in parse_bhavcopy_equity(payload, symbols, day):
                    candle = _equity_candle(record.tradingsymbol, day, record)
                    if candle is not None:
                        accumulator[record.tradingsymbol].append(candle)
        day += timedelta(days=1)
    logger.info("equity_history_fetched", days_fetched=days_fetched, symbols_found=len(accumulator))
    return {symbol: tuple(candles) for symbol, candles in accumulator.items()}

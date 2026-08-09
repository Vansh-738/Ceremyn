"""Free, credential-less equity OHLCV history via NSE cash-market bhavcopy.

One bhavcopy download per trading day covers every wanted symbol -- not one
download per symbol, which would mean hundreds of thousands of redundant
downloads at whole-market scale. `symbols=None` scans the entire real listed
equity universe found in each day's file rather than a hand-picked list.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

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


DEFAULT_TURNOVER_WINDOW = 20  # ~1 trading month -- a standard liquidity-screening lookback


def filter_by_min_avg_turnover(
    candles_by_symbol: dict[str, tuple[Candle, ...]],
    min_avg_daily_turnover: Decimal,
    *,
    window: int = DEFAULT_TURNOVER_WINDOW,
) -> dict[str, tuple[Candle, ...]]:
    """Keep only symbols currently liquid enough, trimmed to the trailing run of
    bars where they were.

    A liquidity floor, not a market-cap one: thin daily turnover (close price x
    volume) is what makes a stock cheap to move with a small amount of money,
    regardless of nominal market cap. Judged bar-by-bar via a trailing
    `window`-day average -- deliberately never a single average over the whole
    fetched history. A whole-history average lets a stock's FUTURE turnover
    justify scanning its past: a stock that only became liquid partway through
    the lookback would have its earlier, illiquid history folded into
    pattern/hit-rate stats anyway, and a single early volume spike could carry
    an otherwise-thin stock's entire average. Here, a symbol is dropped
    outright if its most recent `window`-day average doesn't clear the floor
    (not tradeable right now, regardless of past history), and otherwise
    trimmed to the contiguous run of trailing bars whose own `window`-day
    trailing average cleared the floor -- so an early illiquid stretch never
    contributes occurrences to the kept history. Symbols with fewer than
    `window` bars can't be assessed at all and are dropped.
    """
    kept: dict[str, tuple[Candle, ...]] = {}
    for symbol, candles in candles_by_symbol.items():
        n = len(candles)
        if n < window:
            continue
        turnovers = [c.close * c.volume for c in candles]
        floor = min_avg_daily_turnover * window
        running = sum(turnovers[:window], Decimal(0))
        liquid_at: dict[int, bool] = {window - 1: running >= floor}
        for i in range(window, n):
            running += turnovers[i] - turnovers[i - window]
            liquid_at[i] = running >= floor
        if not liquid_at[n - 1]:
            continue
        start = n - 1
        while start - 1 >= window - 1 and liquid_at[start - 1]:
            start -= 1
        kept[symbol] = candles[start:]
    return kept

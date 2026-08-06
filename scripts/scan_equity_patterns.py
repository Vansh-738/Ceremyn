"""Runnable demo: scan real NSE equity data for candlestick patterns, on its own.

No manual chart-feeding -- downloads real NSE cash-market bhavcopy for a watchlist,
builds candle history, detects every TA-Lib candlestick pattern, attaches the
pattern's own historical hit rate (backtested against the same history, not
asserted), and prints RSI at the moment each pattern fired.

This is read-only market intelligence (see ARCHITECTURE_DECISIONS.md /
ROADMAP_V2.md): it detects and studies patterns, never places or even proposes a
concrete order. Nothing here is investment advice.

Usage:
    .venv/bin/python scripts/scan_equity_patterns.py --start 2026-02-01 --end 2026-08-05 \
        --symbols RELIANCE TCS INFY
"""

import argparse
import asyncio
from datetime import date, datetime, time, timedelta

from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.exceptions import DataError
from ceremyn.core.timeutils import IST, to_ist
from ceremyn.data.providers.bhavcopy import EquityBhavcopyClient, parse_bhavcopy_equity
from ceremyn.data.records import EodEquityRecord
from ceremyn.domain import Candle, TimeFrame
from ceremyn.features import indicators
from ceremyn.patterns import PatternPerformance, detect, historical_performance

CLOSE_TIME = time(15, 30)
FORWARD_DAYS = 5
RSI_PERIOD = 14
RECENT_WINDOW_DAYS = 14


def _candle(symbol: str, trade_date: date, record: EodEquityRecord) -> Candle | None:
    if record.close is None:
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


async def _fetch_candles(symbol: str, start: date, end: date) -> tuple[Candle, ...]:
    calendar = MarketCalendar()
    client = EquityBhavcopyClient()
    candles: list[Candle] = []
    day = start
    while day <= end:
        if calendar.is_trading_day(day):
            try:
                payload = await client.download(day)
            except DataError:
                pass
            else:
                for record in parse_bhavcopy_equity(payload, (symbol,), day):
                    candle = _candle(symbol, day, record)
                    if candle is not None:
                        candles.append(candle)
        day += timedelta(days=1)
    return tuple(candles)


def _rsi_at(candles: tuple[Candle, ...], index: int) -> float | None:
    closes = [float(c.close) for c in candles[: index + 1]]
    return indicators.rsi(closes, period=RSI_PERIOD)


def _performance_note(perf: PatternPerformance | None) -> str:
    if perf is None:
        return "no historical study available"
    if perf.is_significant and perf.hit_rate is not None:
        return (
            f"historically preceded a {perf.average_forward_return_pct:+.1f}% move "
            f"over {FORWARD_DAYS} days in {perf.hit_rate:.0%} of {perf.occurrences} "
            f"past occurrences"
        )
    return f"only {perf.occurrences} historical occurrence(s) -- not enough to trust a rate yet"


async def scan_symbol(symbol: str, start: date, end: date) -> None:
    candles = await _fetch_candles(symbol, start, end)
    print(f"\n=== {symbol}: {len(candles)} trading day(s) fetched ===")
    if len(candles) < 20:
        print("  Not enough history to detect patterns reliably (need 20+ bars).")
        return

    patterns = detect(candles, tradingsymbol=symbol)
    performance = {
        (p.pattern_name, p.direction): p
        for p in historical_performance(candles, patterns, forward_days=FORWARD_DAYS)
    }
    index_by_timestamp = {c.timestamp: i for i, c in enumerate(candles)}

    print(f"  {len(patterns)} pattern occurrence(s) detected across history.")
    recent_cutoff = candles[-1].timestamp - timedelta(days=RECENT_WINDOW_DAYS)
    recent = sorted(
        (p for p in patterns if p.detected_at >= recent_cutoff), key=lambda p: p.detected_at
    )
    if not recent:
        print(f"  No patterns in the last {RECENT_WINDOW_DAYS} days of this window.")
        return

    print("  Recent occurrences:")
    for pattern in recent:
        index = index_by_timestamp.get(pattern.detected_at)
        rsi_value = _rsi_at(candles, index) if index is not None else None
        rsi_note = f"RSI {rsi_value:.0f}" if rsi_value is not None else "RSI n/a"
        perf_note = _performance_note(performance.get((pattern.name, pattern.direction)))
        print(
            f"    {to_ist(pattern.detected_at):%Y-%m-%d} {pattern.direction.value:>7s} "
            f"{pattern.name:20s} {rsi_note:9s} -- {perf_note}"
        )


async def main(symbols: list[str], start: date, end: date) -> None:
    for symbol in symbols:
        await scan_symbol(symbol, start, end)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.symbols, args.start, args.end))

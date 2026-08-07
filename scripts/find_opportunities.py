"""Runnable demo: find and rank opportunities across equities AND commodities, live.

Combines two real data sources into one ranked watchlist:
  - Equities: NSE cash-market bhavcopy (free, no credentials needed).
  - Commodities: MCX futures via the operator's own Kite Connect account (real
    market data the account is already entitled to -- requires Kite API key +
    access token in .env, and the account's MCX segment to be enabled).

For each symbol, detects every TA-Lib candlestick pattern, keeps only the ones
that fired on the LATEST bar, attaches each one's own backtested hit rate, and
ranks everything -- equities and commodities together -- by expected edge. This
is read-only market intelligence (see ARCHITECTURE_DECISIONS.md / ROADMAP_V2.md):
it ranks what's worth a look, never places or proposes a concrete order.

Usage:
    .venv/bin/python scripts/find_opportunities.py --start 2026-02-01 --end 2026-08-05 \
        --equities RELIANCE TCS INFY --commodities CRUDEOIL GOLD SILVER
"""

import argparse
import asyncio
from datetime import date, datetime, time, timedelta

from ceremyn.config import get_settings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.exceptions import BrokerError, DataError
from ceremyn.core.timeutils import IST, now_utc, to_ist
from ceremyn.data.providers.bhavcopy import EquityBhavcopyClient, parse_bhavcopy_equity
from ceremyn.data.providers.kite import KiteProvider
from ceremyn.data.records import EodEquityRecord
from ceremyn.domain import Candle, Opportunity, TimeFrame
from ceremyn.domain.enums import AssetClass
from ceremyn.patterns import find_opportunities

CLOSE_TIME = time(15, 30)
FORWARD_DAYS = 5
MIN_OCCURRENCES = 10


def _equity_candle(symbol: str, trade_date: date, record: EodEquityRecord) -> Candle | None:
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


async def fetch_equity_candles(symbol: str, start: date, end: date) -> tuple[Candle, ...]:
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
                    candle = _equity_candle(symbol, day, record)
                    if candle is not None:
                        candles.append(candle)
        day += timedelta(days=1)
    return tuple(candles)


async def fetch_commodity_candles(
    provider: KiteProvider, name: str, start: date, end: date
) -> tuple[Candle, ...]:
    """The nearest-expiry (most liquid, "active month") contract for `name`."""
    contracts = await provider.fetch_commodity_contracts((name,))
    today = to_ist(now_utc()).date()
    upcoming = sorted((c for c in contracts if c.expiry >= today), key=lambda c: c.expiry)
    if not upcoming or upcoming[0].broker_token is None:
        return ()
    contract = upcoming[0]
    start_dt = datetime.combine(start, time(0, 0), tzinfo=IST)
    end_dt = datetime.combine(end, time(23, 59), tzinfo=IST)
    return tuple(
        await provider.historical_candles(
            contract.broker_token, name, TimeFrame.DAY, start_dt, end_dt
        )
    )


def _print_ranked(opportunities: tuple[Opportunity, ...]) -> None:
    if not opportunities:
        print("No opportunities cleared the minimum-evidence bar in this window.")
        return
    print(
        f"\n{'RANK':<5}{'SYMBOL':<14}{'ASSET':<11}{'PATTERN':<20}{'DIR':<9}"
        f"{'HIT%':>7}{'AVG MOVE':>10}{'N':>5}"
    )
    for i, o in enumerate(opportunities, start=1):
        print(
            f"{i:<5}{o.tradingsymbol:<14}{o.asset_class.value:<11}{o.pattern_name:<20}"
            f"{o.direction.value:<9}{o.hit_rate * 100:>6.0f}%{o.average_forward_return_pct:>+9.1f}%"
            f"{o.occurrences:>5}"
        )


async def main(equities: list[str], commodities: list[str], start: date, end: date) -> None:
    candles_by_symbol: dict[str, tuple[Candle, ...]] = {}
    asset_class_by_symbol: dict[str, AssetClass] = {}

    for symbol in equities:
        candles = await fetch_equity_candles(symbol, start, end)
        print(f"{symbol}: {len(candles)} equity trading day(s) fetched (NSE bhavcopy)")
        if candles:
            candles_by_symbol[symbol] = candles
            asset_class_by_symbol[symbol] = AssetClass.EQUITY

    if commodities:
        settings = get_settings()
        try:
            provider = KiteProvider.from_settings(settings)
        except BrokerError as exc:
            print(f"\nSkipping commodities: {exc}")
        else:
            for name in commodities:
                try:
                    candles = await fetch_commodity_candles(provider, name, start, end)
                except BrokerError as exc:
                    print(f"{name}: FAILED -- {exc}")
                    continue
                print(f"{name}: {len(candles)} commodity trading day(s) fetched (MCX via Kite)")
                if candles:
                    candles_by_symbol[name] = candles
                    asset_class_by_symbol[name] = AssetClass.COMMODITY

    opportunities = find_opportunities(
        candles_by_symbol,
        asset_class_by_symbol,
        forward_days=FORWARD_DAYS,
        min_occurrences=MIN_OCCURRENCES,
    )
    _print_ranked(opportunities)
    if opportunities:
        top = opportunities[0]
        print(
            f"\nTop-ranked: {top.tradingsymbol} {top.pattern_name} ({top.direction.value}), "
            f"detected {to_ist(top.detected_at):%Y-%m-%d} -- historically {top.hit_rate:.0%} hit "
            f"rate, {top.average_forward_return_pct:+.1f}% avg move over {FORWARD_DAYS} days "
            f"across {top.occurrences} past occurrences. Not investment advice."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--equities", nargs="*", default=[])
    parser.add_argument("--commodities", nargs="*", default=[])
    args = parser.parse_args()
    asyncio.run(main(args.equities, args.commodities, args.start, args.end))

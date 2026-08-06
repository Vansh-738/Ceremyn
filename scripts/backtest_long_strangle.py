"""Backtest `long_strangle` against real NSE EOD bhavcopy data (no Postgres needed).

Downloads each trading day's bhavcopy directly via `BhavcopyClient`, builds one
`OptionChainSnapshot` per day (nearest expiry, full strike range), and runs the
exact same `BacktestRunner` -> `RiskEngine` -> `ExecutionSimulator` pipeline the
live/paper runtime uses -- so the real ₹40,000 margin cap applies here too.

EOD granularity: one chain per trading day (the close), not intraday ticks --
the strategy only gets one look per day, unlike the live poller's per-minute view.

Usage:
    .venv/bin/python scripts/backtest_long_strangle.py --start 2026-06-16 --end 2026-07-15
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import structlog

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import OptionChainEvent
from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.config import get_settings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.exceptions import DataError
from ceremyn.core.timeutils import IST
from ceremyn.data.providers.bhavcopy import BhavcopyClient, parse_bhavcopy
from ceremyn.data.records import EodOptionRecord
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import (
    ChainEntry,
    Exchange,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Quote,
    StrategyDefinition,
)
from ceremyn.risk import RiskEngine
from ceremyn.strategies import create

logger = structlog.get_logger(__name__)

UNDERLYING = "NIFTY"
CLOSE_TIME = time(15, 30)


def _contract(record: EodOptionRecord) -> OptionContract:
    suffix = record.option_type
    return OptionContract(
        tradingsymbol=(
            f"{record.underlying}{record.expiry:%y%b%d}{int(record.strike)}{suffix}".upper()
        ),
        exchange=Exchange.NFO,
        underlying=record.underlying,
        expiry=record.expiry,
        strike=record.strike,
        option_type=OptionType(record.option_type),
        # NSE revises this periodically -- read per-row from bhavcopy's own
        # NewBrdLotQty rather than a hardcoded constant, or a multi-year backtest
        # silently uses one snapshot-in-time value for its entire history.
        lot_size=record.lot_size,
    )


def _day_snapshot(
    day: date,
    records: list[EodOptionRecord],
    analytics: ChainAnalyticsService,
    underlying: str = UNDERLYING,
) -> OptionChainSnapshot | None:
    by_expiry: dict[date, list[EodOptionRecord]] = defaultdict(list)
    for record in records:
        by_expiry[record.expiry].append(record)
    upcoming = sorted(expiry for expiry in by_expiry if expiry >= day)
    if not upcoming:
        return None
    nearest = upcoming[0]
    rows = by_expiry[nearest]
    timestamp = datetime.combine(day, CLOSE_TIME, tzinfo=IST)
    entries = []
    spot: Decimal | None = None
    for row in rows:
        price = row.close or row.settle
        if price is None or price <= 0:
            continue
        contract = _contract(row)
        entries.append(
            ChainEntry(
                contract=contract,
                quote=Quote(
                    tradingsymbol=contract.tradingsymbol,
                    timestamp=timestamp,
                    last_price=price,
                    volume=row.volume,
                    open_interest=row.open_interest,
                ),
            )
        )
        if spot is None and row.underlying_close is not None:
            spot = row.underlying_close
    if not entries or spot is None:
        return None
    snapshot = OptionChainSnapshot(
        underlying=underlying,
        expiry=nearest,
        spot=spot,
        timestamp=timestamp,
        entries=tuple(entries),
    )
    return analytics.enrich(snapshot)


async def _fetch_events(
    start: date, end: date, analytics: ChainAnalyticsService, underlying: str = UNDERLYING
) -> list[OptionChainEvent]:
    calendar = MarketCalendar()
    client = BhavcopyClient()
    events: list[OptionChainEvent] = []
    day = start
    while day <= end:
        if calendar.is_trading_day(day):
            try:
                payload = await client.download(day)
            except DataError as exc:
                logger.warning("bhavcopy_skip", trade_date=str(day), reason=str(exc))
            else:
                records = parse_bhavcopy(payload, (underlying,), day)
                snapshot = _day_snapshot(day, records, analytics, underlying=underlying)
                if snapshot is not None:
                    events.append(OptionChainEvent(timestamp=snapshot.timestamp, chain=snapshot))
        day += timedelta(days=1)
    return events


async def main(start: date, end: date) -> None:
    settings = get_settings()
    analytics = ChainAnalyticsService(risk_free_rate=settings.data.risk_free_rate)
    events = await _fetch_events(start, end, analytics)
    print(f"Fetched {len(events)} trading day(s) of real NIFTY bhavcopy data.")
    if not events:
        print("No data — nothing to backtest.")
        return

    definition = StrategyDefinition(
        id="long_strangle_backtest",
        strategy_type="long_strangle",
        name="Long Strangle (backtest)",
        underlyings=(UNDERLYING,),
        params={},
    )
    risk_engine = RiskEngine(settings)
    config = BacktestConfig(
        portfolio=PortfolioConfig(
            initial_cash=settings.portfolio.initial_cash,
            short_option_margin_ratio=settings.risk.margin.short_option_margin_ratio,
            long_option_margin_ratio=settings.risk.margin.long_option_margin_ratio,
        )
    )
    report = BacktestRunner(
        strategy=create(definition), definition=definition, risk_engine=risk_engine, config=config
    ).run(events)

    print(report.performance_report)
    print(f"trades closed:   {len(report.trade_ledger)}")
    print(f"risk decisions:  {report.strategy_summary['risk_decisions']}")
    print(f"final cash:      {report.final_portfolio.buying_power}")
    for trade in report.trade_ledger:
        net_pnl = trade.gross_pnl - trade.costs
        print(
            f"  {trade.contract.tradingsymbol}: entry {trade.entry_price} -> "
            f"exit {trade.exit_price}, net pnl {net_pnl}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))

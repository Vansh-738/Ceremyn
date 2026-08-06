"""Backtest every registered strategy against the same real NSE bhavcopy window.

Reuses `backtest_long_strangle.py`'s data-fetch/conversion logic so there is one
source of real historical chains, not nine parallel copies of the same code.
Runs each strategy with its default params against the exact real ₹40,000
account + risk settings from `.env` -- so a strategy that needs to sell a leg
gets rejected here exactly as it would live, with the real reason why.

Usage:
    .venv/bin/python scripts/backtest_all_strategies.py --start 2026-06-16 --end 2026-07-15
"""

import argparse
import asyncio
from datetime import date

from backtest_long_strangle import UNDERLYING, _fetch_events

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.config import get_settings
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import StrategyDefinition
from ceremyn.risk import RiskEngine
from ceremyn.strategies import available_types, create


async def main(start: date, end: date) -> None:
    settings = get_settings()
    analytics = ChainAnalyticsService(risk_free_rate=settings.data.risk_free_rate)
    events = await _fetch_events(start, end, analytics)
    print(f"Fetched {len(events)} trading day(s) of real NIFTY bhavcopy data.\n")
    if not events:
        print("No data — nothing to backtest.")
        return

    config = BacktestConfig(
        portfolio=PortfolioConfig(
            initial_cash=settings.portfolio.initial_cash,
            short_option_margin_ratio=settings.risk.margin.short_option_margin_ratio,
            long_option_margin_ratio=settings.risk.margin.long_option_margin_ratio,
        )
    )

    for strategy_type in available_types():
        definition = StrategyDefinition(
            id=f"{strategy_type}_survey",
            strategy_type=strategy_type,
            name=f"{strategy_type} (survey)",
            underlyings=(UNDERLYING,),
            params={},
        )
        risk_engine = RiskEngine(settings)
        runner = BacktestRunner(
            strategy=create(definition),
            definition=definition,
            risk_engine=risk_engine,
            config=config,
        )
        print(f"=== {strategy_type} ===")
        try:
            report = runner.run(events)
        except Exception as exc:
            print(f"  CRASHED: {exc!r}\n")
            continue

        rejections = [d for d in runner.engine.risk_decisions if not d.approved]
        print(f"  signals evaluated: {len(runner.engine.risk_decisions)}")
        print(f"  signals rejected:  {len(rejections)}")
        if rejections:
            sample = rejections[0].violations
            print(f"  sample rejection:  {sample}")
        print(f"  trades closed:     {len(report.trade_ledger)}")
        if report.trade_ledger:
            net_pnl = sum(t.gross_pnl - t.costs for t in report.trade_ledger)
            print(f"  net pnl:           {net_pnl}")
            print(f"  final cash:        {report.final_portfolio.buying_power}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))

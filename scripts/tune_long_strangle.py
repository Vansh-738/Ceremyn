"""Grid-search `long_strangle`'s params against one real historical data pull.

Fetches the bhavcopy window once, then runs several parameter combinations
against the exact same events -- reuses `backtest_long_strangle.py`'s fetch/
convert logic so there is one source of real data, not N parallel copies.

Usage:
    .venv/bin/python scripts/tune_long_strangle.py --start 2026-04-16 --end 2026-07-15
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
from ceremyn.strategies import create

CANDIDATES: dict[str, dict[str, object]] = {
    "baseline (defaults)": {},
    "tighter stop, bigger target": {"profit_target_pct": 75.0, "stop_loss_pct": 30.0},
    "wider OTM (cheaper, delta 0.12)": {"target_delta": 0.12},
    "closer to ATM (delta 0.30)": {"target_delta": 0.30},
    "enter fresh each cycle (DTE 5-7)": {"entry_dte_min": 5, "entry_dte_max": 7},
    "wider OTM + tighter stop": {
        "target_delta": 0.12,
        "profit_target_pct": 75.0,
        "stop_loss_pct": 30.0,
    },
    "fresh cycle + tighter stop": {
        "entry_dte_min": 5,
        "entry_dte_max": 7,
        "profit_target_pct": 75.0,
        "stop_loss_pct": 30.0,
    },
}


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

    for label, params in CANDIDATES.items():
        definition = StrategyDefinition(
            id="long_strangle_tune",
            strategy_type="long_strangle",
            name="Long Strangle (tune)",
            underlyings=(UNDERLYING,),
            params=params,
        )
        risk_engine = RiskEngine(settings)
        runner = BacktestRunner(
            strategy=create(definition),
            definition=definition,
            risk_engine=risk_engine,
            config=config,
        )
        report = runner.run(events)
        net_pnl = sum(t.gross_pnl - t.costs for t in report.trade_ledger)
        wins = sum(1 for t in report.trade_ledger if t.gross_pnl - t.costs > 0)
        print(f"=== {label} ===")
        print(f"  params:        {params or 'defaults'}")
        print(f"  trades closed: {len(report.trade_ledger)}  (wins: {wins})")
        print(f"  net pnl:       {net_pnl}")
        print(f"  final cash:    {report.final_portfolio.buying_power}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))

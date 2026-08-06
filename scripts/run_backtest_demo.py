"""Runnable demo: backtest a real registered strategy end-to-end.

No Postgres, no Kite credentials, no Docker — this builds a small synthetic
option-chain price path by hand and runs it through the exact same
`BacktestRunner` -> `RiskEngine` -> `ExecutionSimulator` -> `IndianCostModel`
pipeline a real bhavcopy-backed backtest uses. It exists to answer "does this
thing actually work" in under a second, and as a template for wiring in real
NSE bhavcopy data later (see `scripts/ingest_bhavcopy.py`).

Strategy: `expiry_day_theta` — sells an ATM straddle on the expiry day itself
and exits on a profit target, a stop loss, or a fixed time — chosen for this
demo because it needs only ATM quotes (no greeks/IV-rank machinery to fake).

Usage:
    .venv/bin/python scripts/run_backtest_demo.py
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import OptionChainEvent
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.config.settings import Settings
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

EXPIRY = date(2026, 7, 21)  # the backtest's "today" is also the expiry date
STRIKE = Decimal("25000")


def _contract(option_type: OptionType) -> OptionContract:
    suffix = "CE" if option_type is OptionType.CALL else "PE"
    return OptionContract(
        tradingsymbol=f"NIFTY26JUL25000{suffix}",
        exchange=Exchange.NFO,
        underlying="NIFTY",
        expiry=EXPIRY,
        strike=STRIKE,
        option_type=option_type,
        lot_size=25,
    )


def _chain(*, timestamp: datetime, call_mid: str, put_mid: str) -> OptionChainSnapshot:
    call, put = _contract(OptionType.CALL), _contract(OptionType.PUT)

    def quote(contract: OptionContract, mid: str) -> Quote:
        mid_price = Decimal(mid)
        return Quote(
            tradingsymbol=contract.tradingsymbol,
            timestamp=timestamp,
            last_price=mid_price,
            bid=mid_price - Decimal("2"),
            ask=mid_price + Decimal("2"),
            volume=500,
            open_interest=2000,
        )

    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=EXPIRY,
        spot=STRIKE,
        timestamp=timestamp,
        entries=(
            ChainEntry(contract=call, quote=quote(call, call_mid)),
            ChainEntry(contract=put, quote=quote(put, put_mid)),
        ),
    )


def main() -> None:
    definition = StrategyDefinition(
        id="expiry_theta_demo",
        strategy_type="expiry_day_theta",
        name="Expiry-Day Theta (demo)",
        underlyings=("NIFTY",),
        params={"profit_target_pct": 60.0, "stop_loss_pct": 40.0},
    )
    strategy = create(definition)
    settings = Settings(_env_file=None)
    # Two real risk rules would otherwise (correctly) block this demo: expiry-day
    # trading is disabled by default (this strategy IS an expiry-day strategy, so a
    # real deployment enables it deliberately), and a single-underlying demo always
    # reads as 100% concentrated against the default 60% cross-underlying limit.
    settings.risk.time.allow_expiry_day = True
    settings.risk.time.min_days_to_expiry = 0  # this strategy trades AT expiry (DTE 0) by design
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    risk_engine = RiskEngine(settings)

    entry_at = datetime(2026, 7, 21, 4, 35, tzinfo=UTC)  # 10:05 IST
    exit_at = datetime(2026, 7, 21, 7, 30, tzinfo=UTC)  # 13:00 IST — decayed premium

    events = (
        OptionChainEvent(
            timestamp=entry_at,
            chain=_chain(timestamp=entry_at, call_mid="155", put_mid="145"),
        ),
        OptionChainEvent(
            timestamp=exit_at,
            chain=_chain(timestamp=exit_at, call_mid="60", put_mid="55"),
        ),
    )

    report = BacktestRunner(
        strategy=strategy, definition=definition, risk_engine=risk_engine, config=BacktestConfig()
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
    main()

"""One-off demo: submit a real buy-then-sell paper trade using live Kite prices,
then start the dashboard server carrying that trade — so you can see exactly
what a completed trade looks like without waiting for the strategy's own timing.

This goes through the real risk engine and real OMS (same pipeline the
strategy and REST poller use) — it is a manually-triggered demonstration, not
an automatic strategy decision. Safe to run any time; buys/sells one lot of a
near-the-money NIFTY option and closes it moments later, all in simulation.

Usage:
    .venv/bin/python scripts/demo_paper_trade.py
"""

import asyncio
import contextlib
import time
from uuid import uuid4

import uvicorn

from ceremyn.api.app import create_app
from ceremyn.config import get_settings
from ceremyn.core.container import Container
from ceremyn.core.timeutils import now_ist, now_utc
from ceremyn.domain import (
    ChainEntry,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Side,
    Signal,
    SignalAction,
    SignalLeg,
)


async def _pick_atm_call(container: Container) -> OptionContract:
    contracts = await container.kite_provider.fetch_option_contracts(
        list(container.settings.data.underlyings[:1])
    )
    spot = await container.kite_provider.spot_price("NIFTY")
    today = now_ist().date()
    nearest_expiry = min(c.expiry for c in contracts if c.expiry >= today)
    calls = [
        c for c in contracts if c.expiry == nearest_expiry and c.option_type is OptionType.CALL
    ]
    return min(calls, key=lambda c: abs(c.strike - spot))


async def _quote_chain(container: Container, contract: OptionContract) -> OptionChainSnapshot:
    symbol = f"{contract.exchange.value}:{contract.tradingsymbol}"
    quotes = await container.kite_provider.quotes([symbol])
    spot = await container.kite_provider.spot_price("NIFTY")
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=contract.expiry,
        spot=spot,
        timestamp=now_utc(),
        entries=(ChainEntry(contract=contract, quote=quotes.get(symbol)),),
    )


def _apply_fills(container: Container) -> None:
    broker = container.oms_engine.router.brokers[0]
    for report in broker.fetch_fills():
        with contextlib.suppress(KeyError):
            container.oms_engine.process_execution_report(report)


async def main() -> None:
    settings = get_settings()
    if not settings.kite.api_key or not settings.kite.access_token.get_secret_value():
        raise SystemExit("Kite API key + access token must be configured first.")

    container = Container(settings)
    contract = await _pick_atm_call(container)
    print(f"Using {contract.tradingsymbol} (expiry {contract.expiry}, strike {contract.strike})")

    entry_chain = await _quote_chain(container, contract)
    container.live_engine.cache.set_chain(entry_chain)
    correlation_id = uuid4()

    entry_signal = Signal(
        strategy_id="demo_trade",
        signal_type=SignalAction.ENTER,
        created_at=now_utc(),
        market_timestamp=now_utc(),
        legs=(SignalLeg(contract=contract, side=Side.BUY, lots=1),),
        reason="manual demo trade",
        correlation_id=correlation_id,
    )
    (entry_order,) = container.oms_engine.submit_signal(entry_signal, now=now_utc())
    time.sleep(1)  # the simulated broker has a 0.5s order-latency window, same as a real one
    _apply_fills(container)
    filled_entry = container.oms_engine.orders[entry_order.oms_order_id]
    print(f"Entry: {filled_entry.execution_state.value}, filled qty {filled_entry.filled_quantity}")

    print("Waiting 15s for the price to move before closing...")
    time.sleep(15)

    exit_chain = await _quote_chain(container, contract)
    container.live_engine.cache.set_chain(exit_chain)
    exit_signal = Signal(
        strategy_id="demo_trade",
        signal_type=SignalAction.EXIT,
        created_at=now_utc(),
        market_timestamp=now_utc(),
        legs=(SignalLeg(contract=contract, side=Side.SELL, lots=1),),
        reason="manual demo trade close",
        correlation_id=correlation_id,
    )
    (exit_order,) = container.oms_engine.submit_signal(exit_signal, now=now_utc())
    time.sleep(1)
    _apply_fills(container)
    filled_exit = container.oms_engine.orders[exit_order.oms_order_id]
    print(f"Exit: {filled_exit.execution_state.value}, filled qty {filled_exit.filled_quantity}")

    snapshot = container.oms_engine.portfolio.snapshot()
    print(f"Realized P&L so far: {snapshot.realized_pnl}")
    print(f"Buying power: {snapshot.buying_power}")

    print("\nStarting dashboard server with this trade already loaded...")
    app = create_app(settings, container=container)
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())

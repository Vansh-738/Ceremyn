"""Trading mode model.

The mode determines which subsystems run and, critically, whether real orders
can ever reach a broker. See `Settings.effective_mode` for the gating logic.
"""

from enum import StrEnum


class TradingMode(StrEnum):
    """Operating mode of the platform.

    RESEARCH: data ingestion, analytics, backtesting, reports. No order
        management system runs at all.
    PAPER: live market data, simulated fills via the paper broker, full risk
        engine, journal. Mandatory burn-in stage for every strategy.
    LIVE: real orders via Kite Connect. Reachable only when every live-trading
        gate passes; otherwise the platform degrades to PAPER.
    """

    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"

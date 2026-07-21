"""Glue between simulated fills, the portfolio, and fill events.

A `VirtualFill` from the broker carries everything needed to book the fill into the
portfolio and to describe it as an `OrderFilled` event. This module keeps that mapping
in one place so the engine stays declarative.
"""

from datetime import datetime

from ceremyn.backtest.fills import VirtualFill
from ceremyn.paper.events import OrderFilled
from ceremyn.paper.portfolio import PaperPortfolio


def apply_virtual_fill(portfolio: PaperPortfolio, virtual_fill: VirtualFill) -> None:
    """Book a simulated fill into the portfolio using the reused accounting."""
    portfolio.apply_fill(
        fill=virtual_fill.fill,
        order=virtual_fill.updated_order,
        strategy_id=virtual_fill.strategy_id,
        signal_id=virtual_fill.signal_id,
        costs=virtual_fill.cost_breakdown.total,
    )


def fill_event(virtual_fill: VirtualFill, *, submitted_at: datetime) -> OrderFilled:
    return OrderFilled(
        order=virtual_fill.updated_order,
        fill=virtual_fill.fill,
        costs=virtual_fill.cost_breakdown,
        submitted_at=submitted_at,
        strategy_id=virtual_fill.strategy_id,
    )

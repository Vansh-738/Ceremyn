from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.backtest.commission import CostBreakdown
from alphaquant.domain import Fill, Order, Side
from alphaquant.domain.enums import OrderStatus, OrderType
from alphaquant.paper.events import MarketTick, OrderFilled
from tests.unit.backtest.helpers import make_chain, make_contract
from tests.unit.paper.conftest import TICK_ZERO


def test_market_tick_requires_aware_timestamp() -> None:
    chain = make_chain(timestamp=TICK_ZERO, last_price="100", bid="99", ask="101")
    with pytest.raises(ValidationError):
        MarketTick(as_of=datetime(2026, 7, 14, 10, 0), underlying="NIFTY", chain=chain)


def test_order_filled_latency() -> None:
    order = Order(
        contract=make_contract(),
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created_at=TICK_ZERO,
    )
    event = OrderFilled(
        order=order,
        fill=Fill(
            order_id=order.id,
            quantity=25,
            price=Decimal("100"),
            timestamp=TICK_ZERO + timedelta(seconds=3),
        ),
        costs=CostBreakdown(),
        submitted_at=TICK_ZERO,
        strategy_id="s",
    )
    assert event.latency_seconds == 3.0

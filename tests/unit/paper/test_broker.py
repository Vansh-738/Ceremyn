from datetime import timedelta
from decimal import Decimal

from ceremyn.backtest.fills import ExecutionContext
from ceremyn.domain.enums import OrderStatus, OrderType, Side
from ceremyn.paper.broker import PaperBroker, PaperBrokerConfig
from tests.unit.paper.conftest import TICK_ZERO, make_market_order, make_tick


def context_at(index: int) -> ExecutionContext:
    tick = make_tick(index, "100")
    return ExecutionContext(timestamp=tick.as_of, chain=tick.chain)


class TestQueueAndLatency:
    def test_order_rests_in_queue_until_eligible(self) -> None:
        broker = PaperBroker(PaperBrokerConfig(latency_seconds=10))
        order = make_market_order()
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        assert broker.has_open(order.id)
        # Before the latency window elapses, no fill.
        fills = broker.process(context=context_at(0), now=TICK_ZERO + timedelta(seconds=5))
        assert fills == ()
        assert broker.has_open(order.id)

    def test_order_fills_after_latency(self) -> None:
        broker = PaperBroker(PaperBrokerConfig(latency_seconds=1))
        order = make_market_order()
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        fills = broker.process(context=context_at(1), now=TICK_ZERO + timedelta(seconds=5))
        assert len(fills) == 1
        assert fills[0].fill.quantity == 25
        assert not broker.has_open(order.id)  # fully filled, dequeued

    def test_open_orders_view(self) -> None:
        broker = PaperBroker()
        order = make_market_order()
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        assert [o.id for o in broker.open_orders] == [order.id]


class TestFillMechanicsReused:
    def test_market_order_fills_at_ask_for_buy(self) -> None:
        broker = PaperBroker(PaperBrokerConfig(latency_seconds=0, slippage_bps=Decimal("0")))
        order = make_market_order(side=Side.BUY)
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        fills = broker.process(context=context_at(0), now=TICK_ZERO)
        # Ask is last + 0.5 = 100.5 (no slippage).
        assert fills[0].fill.price == Decimal("100.5")

    def test_partial_fill_via_volume_participation(self) -> None:
        # 3 lots requested (contract lot_size is 25 -> 75 units); volume 1000 *
        # 0.03 = 30, rounded down to the nearest 25-multiple = 25 -- exactly 1
        # lot. A real broker can never partially fill below one lot's
        # granularity, so the fill must land on a lot boundary, not an
        # arbitrary unit count.
        broker = PaperBroker(PaperBrokerConfig(latency_seconds=0, max_volume_participation=0.03))
        order = make_market_order(quantity=75)
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        fills = broker.process(context=context_at(0), now=TICK_ZERO)
        assert fills[0].fill.quantity == 25
        assert fills[0].updated_order.status is OrderStatus.PARTIALLY_FILLED
        assert broker.has_open(order.id)  # remainder still queued

    def test_limit_order_only_fills_when_marketable(self) -> None:
        from ceremyn.domain import Order
        from tests.unit.backtest.helpers import make_contract

        broker = PaperBroker(PaperBrokerConfig(latency_seconds=0))
        # Buy limit at 90 while ask is 100.5 -> not marketable, rests.
        order = Order(
            contract=make_contract(),
            side=Side.BUY,
            quantity=25,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("90"),
            status=OrderStatus.VALIDATED,
            created_at=TICK_ZERO,
        )
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        assert broker.process(context=context_at(0), now=TICK_ZERO) == ()
        assert broker.has_open(order.id)


class TestCancel:
    def test_cancel_removes_from_queue(self) -> None:
        broker = PaperBroker()
        order = make_market_order()
        broker.submit(order, strategy_id="s", now=TICK_ZERO)
        assert broker.cancel(order.id) is True
        assert not broker.has_open(order.id)

    def test_cancel_unknown_is_false(self) -> None:
        assert PaperBroker().cancel(make_market_order().id) is False

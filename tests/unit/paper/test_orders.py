from datetime import timedelta

from ceremyn.domain import Side, Signal, SignalLeg
from ceremyn.domain.enums import OrderStatus, SignalAction
from ceremyn.paper.broker import PaperBroker
from ceremyn.paper.orders import PaperOMS
from tests.unit.backtest.helpers import make_contract
from tests.unit.paper.conftest import TICK_ZERO


def enter_signal() -> Signal:
    return Signal(
        strategy_id="s",
        signal_type=SignalAction.ENTER,
        created_at=TICK_ZERO,
        legs=(SignalLeg(contract=make_contract(), side=Side.BUY, lots=1),),
        reason="enter",
    )


class TestSubmit:
    def test_submit_signal_creates_and_tracks_orders(self) -> None:
        oms = PaperOMS(PaperBroker())
        orders = oms.submit_signal(enter_signal(), strategy_id="s", now=TICK_ZERO)
        assert len(orders) == 1
        assert orders[0].status is OrderStatus.SUBMITTED
        assert orders[0].id in oms.orders
        assert oms.active_orders == orders

    def test_orders_reach_the_broker_queue(self) -> None:
        broker = PaperBroker()
        oms = PaperOMS(broker)
        orders = oms.submit_signal(enter_signal(), strategy_id="s", now=TICK_ZERO)
        assert broker.has_open(orders[0].id)


class TestLifecycle:
    def test_record_fill_updates_tracked_order(self) -> None:
        oms = PaperOMS(PaperBroker())
        (order,) = oms.submit_signal(enter_signal(), strategy_id="s", now=TICK_ZERO)
        filled = order.transition_to(OrderStatus.OPEN).transition_to(OrderStatus.FILLED)
        oms.record_fill(filled)
        assert oms.orders[order.id].status is OrderStatus.FILLED
        assert oms.active_orders == ()

    def test_cancel_marks_order_cancelled(self) -> None:
        broker = PaperBroker()
        oms = PaperOMS(broker)
        (order,) = oms.submit_signal(enter_signal(), strategy_id="s", now=TICK_ZERO)
        assert oms.cancel(order.id, reason="manual") is True
        assert oms.orders[order.id].status is OrderStatus.CANCELLED
        assert not broker.has_open(order.id)

    def test_cancel_unknown_order_is_false(self) -> None:
        oms = PaperOMS(PaperBroker())
        (order,) = oms.submit_signal(enter_signal(), strategy_id="s", now=TICK_ZERO)
        # Filled order can't be cancelled at the broker (already gone from queue).
        oms._broker.cancel(order.id)
        assert oms.cancel(order.id) is False


def test_orders_from_signal_uses_market_timestamp() -> None:
    oms = PaperOMS(PaperBroker())
    orders = oms.orders_from_signal(enter_signal(), now=TICK_ZERO + timedelta(seconds=10))
    assert orders[0].created_at == TICK_ZERO + timedelta(seconds=10)

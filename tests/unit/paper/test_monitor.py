from datetime import timedelta
from decimal import Decimal

from ceremyn.backtest.commission import CostBreakdown
from ceremyn.domain import Fill, Order, Side, Signal, SignalLeg
from ceremyn.domain.enums import OrderStatus, OrderType, SignalAction
from ceremyn.paper.events import (
    OrderCancelled,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
    SignalGenerated,
)
from ceremyn.paper.monitor import PaperMonitor
from tests.unit.backtest.helpers import make_contract
from tests.unit.paper.conftest import TICK_ZERO


def an_order() -> Order:
    return Order(
        contract=make_contract(),
        side=Side.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created_at=TICK_ZERO,
    )


def filled_event(latency: float) -> OrderFilled:
    order = an_order()
    fill_ts = TICK_ZERO + timedelta(seconds=latency)
    return OrderFilled(
        order=order,
        fill=Fill(order_id=order.id, quantity=25, price=Decimal("100"), timestamp=fill_ts),
        costs=CostBreakdown(),
        submitted_at=TICK_ZERO,
        strategy_id="s",
    )


def a_signal_event(runtime: float) -> SignalGenerated:
    signal = Signal(
        strategy_id="alpha",
        signal_type=SignalAction.ENTER,
        created_at=TICK_ZERO,
        legs=(SignalLeg(contract=make_contract(), side=Side.BUY, lots=1),),
    )
    return SignalGenerated(signal=signal, strategy_id="alpha", runtime_seconds=runtime)


def test_counts_and_fill_rate() -> None:
    monitor = PaperMonitor()
    monitor.on_submitted(OrderSubmitted(order=an_order(), submitted_at=TICK_ZERO))
    monitor.on_submitted(OrderSubmitted(order=an_order(), submitted_at=TICK_ZERO))
    monitor.on_filled(filled_event(2.0))
    monitor.on_rejected(OrderRejected(signal=a_signal_event(0).signal, reason="x"))
    monitor.on_cancelled(OrderCancelled(order_id=an_order().id))

    snap = monitor.snapshot()
    assert snap.submitted == 2
    assert snap.filled == 1
    assert snap.rejected == 1
    assert snap.cancelled == 1
    assert snap.fill_rate == 0.5


def test_latency_stats() -> None:
    monitor = PaperMonitor()
    monitor.on_filled(filled_event(2.0))
    monitor.on_filled(filled_event(4.0))
    snap = monitor.snapshot()
    assert snap.avg_latency_seconds == 3.0
    assert snap.max_latency_seconds == 4.0


def test_strategy_runtime_accumulates() -> None:
    monitor = PaperMonitor()
    monitor.on_signal(a_signal_event(0.01))
    monitor.on_signal(a_signal_event(0.02))
    snap = monitor.snapshot()
    assert snap.signals == 2
    assert snap.strategy_runtime_seconds["alpha"] == round(0.03, 6)


def test_empty_snapshot_defaults() -> None:
    snap = PaperMonitor().snapshot()
    assert snap.fill_rate == 0.0
    assert snap.avg_latency_seconds == 0.0
    assert snap.max_latency_seconds == 0.0

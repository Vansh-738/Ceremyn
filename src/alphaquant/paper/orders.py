"""PaperOMS: turn approved signals into orders and track their lifecycle.

The OMS is the only component that constructs orders (safety invariant: strategies
emit Signals, never orders). Order construction reuses the backtest
`ExecutionSimulator.orders_from_signal`; lifecycle transitions reuse the domain
`Order.transition_to` state machine. The OMS submits orders to the paper broker and
records the terminal state of every order it has seen.
"""

from datetime import datetime
from uuid import UUID

from alphaquant.backtest.simulator import ExecutionSimulator
from alphaquant.domain import Order, Signal
from alphaquant.domain.enums import OrderStatus
from alphaquant.paper.broker import PaperBroker


class PaperOMS:
    def __init__(self, broker: PaperBroker) -> None:
        self._broker = broker
        # A stateless simulator used only to build orders from signals.
        self._builder = ExecutionSimulator()
        self.orders: dict[UUID, Order] = {}

    def orders_from_signal(self, signal: Signal, *, now: datetime) -> tuple[Order, ...]:
        return self._builder.orders_from_signal(signal, created_at=now)

    def submit_signal(
        self, signal: Signal, *, strategy_id: str, now: datetime
    ) -> tuple[Order, ...]:
        """Build orders for an approved signal, submit them, and track them."""
        orders = self.orders_from_signal(signal, now=now)
        submitted: list[Order] = []
        for order in orders:
            # orders_from_signal already marks orders VALIDATED (post risk-check).
            live = order.transition_to(OrderStatus.SUBMITTED)
            self.orders[live.id] = live
            self._broker.submit(live, strategy_id=strategy_id, now=now)
            submitted.append(live)
        return tuple(submitted)

    def record_fill(self, order: Order) -> None:
        """Persist the post-fill order state (FILLED / PARTIALLY_FILLED)."""
        self.orders[order.id] = order

    def cancel(self, order_id: UUID, *, reason: str = "") -> bool:
        """Cancel a resting order; returns True if it was open."""
        if not self._broker.cancel(order_id):
            return False
        existing = self.orders.get(order_id)
        if existing is not None and existing.status not in _TERMINAL:
            self.orders[order_id] = existing.transition_to(OrderStatus.CANCELLED, reason=reason)
        return True

    @property
    def active_orders(self) -> tuple[Order, ...]:
        return tuple(order for order in self.orders.values() if order.status not in _TERMINAL)


_TERMINAL = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED})

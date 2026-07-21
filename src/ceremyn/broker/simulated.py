"""`SimulatedBroker`: a realistic `BrokerAdapter` fallback used whenever the live-trading
gate isn't fully open, so OMS stays functional end-to-end without ever risking a real order.

Fill mechanics are entirely reused from `paper.broker.PaperBroker` (itself a thin real-time
wrapper over the shared `backtest.simulator.ExecutionSimulator`); this module only adds the
bookkeeping (`oms.positions.OMSPortfolio`, order/fill snapshots) needed to satisfy the
`BrokerAdapter` protocol OMS expects. No live order ever leaves this process.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from ceremyn.backtest.fills import ExecutionContext, VirtualFill
from ceremyn.backtest.portfolio import PortfolioConfig
from ceremyn.core.timeutils import now_utc
from ceremyn.domain import Quote
from ceremyn.domain.enums import OrderStatus
from ceremyn.live.cache import LiveDataCache
from ceremyn.oms.broker import (
    BrokerCancelResult,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPositionSnapshot,
    BrokerReplaceResult,
    BrokerSubmissionResult,
)
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand
from ceremyn.oms.positions import OMSPortfolio
from ceremyn.paper.broker import PaperBroker, PaperBrokerConfig

_STATUS_FROM_ORDER: dict[OrderStatus, BrokerOrderStatus] = {
    OrderStatus.OPEN: BrokerOrderStatus.OPEN,
    OrderStatus.PARTIALLY_FILLED: BrokerOrderStatus.PARTIALLY_FILLED,
    OrderStatus.FILLED: BrokerOrderStatus.FILLED,
    OrderStatus.CANCELLED: BrokerOrderStatus.CANCELLED,
    OrderStatus.REJECTED: BrokerOrderStatus.REJECTED,
}


class SimulatedBroker:
    """Fills orders through the reused simulator; never reaches a real exchange."""

    def __init__(
        self,
        *,
        config: PaperBrokerConfig | None = None,
        portfolio_config: PortfolioConfig | None = None,
        market_data: LiveDataCache | None = None,
        name: str = "simulated",
    ) -> None:
        self._name = name
        self._broker = PaperBroker(config)
        self._portfolio = OMSPortfolio(portfolio_config)
        self._market_data = market_data
        self._order_id_by_external: dict[str, UUID] = {}
        self._external_by_order: dict[UUID, str] = {}
        self._correlation_by_order: dict[UUID, UUID | None] = {}
        self._request_hash_by_order: dict[UUID, str] = {}
        self._snapshots: dict[str, BrokerOrderSnapshot] = {}
        self._reports: list[BrokerExecutionReport] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BrokerCapabilities:
        # Bracket legs are just independent orders here, same as a real broker without
        # native OCO support; replace isn't modeled by the underlying simulator.
        return BrokerCapabilities(supports_replace=False, supports_brackets=True)

    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        order = command.order
        external_id = f"sim-{order.id}"
        self._order_id_by_external[external_id] = order.id
        self._external_by_order[order.id] = external_id
        self._correlation_by_order[order.id] = command.correlation_id
        self._request_hash_by_order[order.id] = command.request_hash
        self._broker.submit(order, strategy_id=command.strategy_id, now=command.requested_at)
        self._snapshots[external_id] = BrokerOrderSnapshot(
            external_order_id=external_id,
            status=BrokerOrderStatus.OPEN,
            broker_timestamp=command.requested_at,
            filled_quantity=0,
            remaining_quantity=order.quantity,
            correlation_id=str(command.correlation_id) if command.correlation_id else None,
            request_hash=command.request_hash,
        )
        self._advance(now=command.requested_at)
        return BrokerSubmissionResult(
            external_order_id=external_id, broker_timestamp=command.requested_at
        )

    def cancel(self, command: CancelOrderCommand) -> BrokerCancelResult:
        order_id = self._order_id_by_external.get(command.external_order_id or "")
        cancelled = order_id is not None and self._broker.cancel(order_id)
        if cancelled and command.external_order_id in self._snapshots:
            snapshot = self._snapshots[command.external_order_id]
            self._snapshots[command.external_order_id] = snapshot.model_copy(
                update={"status": BrokerOrderStatus.CANCELLED}
            )
        return BrokerCancelResult(accepted=cancelled, broker_timestamp=command.requested_at)

    def replace(self, command: ReplaceOrderCommand) -> BrokerReplaceResult:
        raise NotImplementedError("simulated broker does not support order replacement")

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None:
        expected = str(command.correlation_id) if command.correlation_id else None
        for snapshot in self._snapshots.values():
            if (
                snapshot.correlation_id == expected
                and snapshot.request_hash == command.request_hash
            ):
                return snapshot
        return None

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]:
        self._advance(now=now_utc())
        return tuple(self._snapshots.values())

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]:
        self._advance(now=now_utc())
        return tuple(self._reports)

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]:
        return tuple(
            BrokerPositionSnapshot(
                tradingsymbol=symbol,
                quantity=position.quantity,
                realized_pnl=position.realized_pnl,
            )
            for symbol, position in self._portfolio.positions.items()
        )

    def fetch_cash(self) -> BrokerCashSnapshot:
        snapshot = self._portfolio.snapshot()
        return BrokerCashSnapshot(
            available_cash=self._portfolio.cash,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
        )

    # -- internal -------------------------------------------------------------

    def _advance(self, *, now: datetime) -> None:
        """Try to fill whatever's eligible, using the best market data available."""
        context = self._build_context(now)
        for virtual_fill in self._broker.process(context=context, now=now):
            self._apply_fill(virtual_fill)

    def _build_context(self, now: datetime) -> ExecutionContext:
        if self._market_data is None:
            return ExecutionContext(timestamp=now)
        underlyings = {order.contract.underlying for order in self._broker.open_orders}
        quotes: dict[str, Quote] = {}
        for underlying in underlyings:
            chain = self._market_data.latest_chain(underlying)
            if chain is None:
                continue
            for entry in chain.entries:
                if entry.quote is not None:
                    quotes[entry.contract.tradingsymbol] = entry.quote
        return ExecutionContext(timestamp=now, quotes=quotes)

    def _apply_fill(self, virtual_fill: VirtualFill) -> None:
        self._portfolio.apply_fill(
            fill=virtual_fill.fill,
            order=virtual_fill.updated_order,
            strategy_id=virtual_fill.strategy_id,
            signal_id=virtual_fill.signal_id,
            costs=virtual_fill.cost_breakdown.total,
        )
        external_id = self._external_by_order.get(virtual_fill.order.id)
        if external_id is None:
            return
        status = _STATUS_FROM_ORDER.get(virtual_fill.updated_order.status, BrokerOrderStatus.OPEN)
        previous = self._snapshots.get(external_id)
        filled = (previous.filled_quantity if previous else 0) + virtual_fill.fill.quantity
        remaining = max(virtual_fill.updated_order.quantity - filled, 0)
        correlation_id = self._correlation_by_order.get(virtual_fill.order.id)
        self._snapshots[external_id] = BrokerOrderSnapshot(
            external_order_id=external_id,
            status=status,
            broker_timestamp=virtual_fill.fill.timestamp,
            filled_quantity=filled,
            remaining_quantity=remaining,
            average_price=virtual_fill.fill.price,
            correlation_id=str(correlation_id) if correlation_id else None,
            request_hash=self._request_hash_by_order.get(virtual_fill.order.id),
        )
        self._reports.append(
            BrokerExecutionReport(
                external_order_id=external_id,
                status=status,
                broker_timestamp=virtual_fill.fill.timestamp,
                fill_id=str(virtual_fill.fill.id),
                last_fill_quantity=virtual_fill.fill.quantity,
                fill_price=virtual_fill.fill.price,
                remaining_quantity=remaining,
            )
        )

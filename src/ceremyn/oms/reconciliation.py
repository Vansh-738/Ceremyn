"""OMS reconciliation across OMS state, broker state, and portfolio accounting."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.domain.enums import Side
from ceremyn.oms.broker import BrokerAdapter, BrokerOrderStatus
from ceremyn.oms.ledger import OMSLedger
from ceremyn.oms.orders import OMSExecutionState, OMSOrder
from ceremyn.oms.positions import OMSPortfolio


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    reconciled: bool
    missing_orders: tuple[str, ...] = ()
    status_drift: dict[str, str] = Field(default_factory=dict)
    position_drift: dict[str, int] = Field(default_factory=dict)
    cash_drift: Decimal = Decimal("0")
    pnl_drift: Decimal = Decimal("0")


class OMSReconciler:
    def reconcile(
        self,
        *,
        orders: tuple[OMSOrder, ...],
        broker: BrokerAdapter,
        ledger: OMSLedger,
        portfolio: OMSPortfolio,
    ) -> ReconciliationReport:
        broker_orders = {snapshot.external_order_id: snapshot for snapshot in broker.fetch_orders()}
        missing: list[str] = []
        status_drift: dict[str, str] = {}
        for order in orders:
            if order.external_order_id is None:
                continue
            snapshot = broker_orders.get(order.external_order_id)
            if snapshot is None:
                missing.append(order.external_order_id)
                continue
            broker_state = _broker_to_oms(snapshot.status)
            if broker_state != order.execution_state:
                status_drift[order.external_order_id] = (
                    f"oms={order.execution_state.value}, broker={broker_state.value}"
                )

        expected_positions: dict[str, int] = {}
        for entry in ledger.fills():
            symbol = str(entry.payload["tradingsymbol"])
            quantity = int(entry.payload["quantity"])
            if entry.payload["side"] == Side.SELL.value:
                quantity = -quantity
            expected_positions[symbol] = expected_positions.get(symbol, 0) + quantity
        actual_positions = {
            symbol: position.quantity
            for symbol, position in portfolio.positions.items()
            if not position.is_flat
        }
        position_drift: dict[str, int] = {}
        for symbol in set(expected_positions) | set(actual_positions):
            if expected_positions.get(symbol, 0) != actual_positions.get(symbol, 0):
                position_drift[symbol] = actual_positions.get(symbol, 0) - expected_positions.get(
                    symbol, 0
                )

        cash = broker.fetch_cash()
        cash_drift = portfolio.cash - cash.available_cash
        pnl_drift = portfolio.snapshot().realized_pnl - cash.realized_pnl
        reconciled = (
            not missing
            and not status_drift
            and not position_drift
            and cash_drift == 0
            and pnl_drift == 0
        )
        return ReconciliationReport(
            reconciled=reconciled,
            missing_orders=tuple(sorted(missing)),
            status_drift=status_drift,
            position_drift=position_drift,
            cash_drift=cash_drift,
            pnl_drift=pnl_drift,
        )


def _broker_to_oms(status: BrokerOrderStatus) -> OMSExecutionState:
    mapping = {
        BrokerOrderStatus.ACKNOWLEDGED: OMSExecutionState.PENDING,
        BrokerOrderStatus.OPEN: OMSExecutionState.PENDING,
        BrokerOrderStatus.PARTIALLY_FILLED: OMSExecutionState.PARTIALLY_FILLED,
        BrokerOrderStatus.FILLED: OMSExecutionState.FILLED,
        BrokerOrderStatus.CANCEL_PENDING: OMSExecutionState.CANCEL_PENDING,
        BrokerOrderStatus.CANCELLED: OMSExecutionState.CANCELLED,
        BrokerOrderStatus.REJECTED: OMSExecutionState.REJECTED,
        BrokerOrderStatus.FAILED: OMSExecutionState.FAILED,
        BrokerOrderStatus.EXPIRED: OMSExecutionState.EXPIRED,
    }
    return mapping[status]

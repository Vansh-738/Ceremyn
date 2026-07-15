"""Placeholder `BrokerAdapter` used until a real broker lands (M13).

Read operations return empty/zero results so OMS reconciliation and metrics stay
meaningful with no broker connected; order-affecting operations raise, since there is
nothing to route an order to yet.
"""

from collections.abc import Sequence
from decimal import Decimal

from alphaquant.oms.broker import (
    BrokerCancelResult,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
    BrokerReplaceResult,
    BrokerSubmissionResult,
)
from alphaquant.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand


class NullBrokerAdapter:
    """No broker is configured. Satisfies `BrokerAdapter` structurally."""

    def __init__(self, name: str = "none") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities()

    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        raise NotImplementedError("no broker configured")

    def cancel(self, command: CancelOrderCommand) -> BrokerCancelResult:
        raise NotImplementedError("no broker configured")

    def replace(self, command: ReplaceOrderCommand) -> BrokerReplaceResult:
        raise NotImplementedError("no broker configured")

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None:
        return None

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]:
        return ()

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]:
        return ()

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]:
        return ()

    def fetch_cash(self) -> BrokerCashSnapshot:
        return BrokerCashSnapshot(available_cash=Decimal("0"))

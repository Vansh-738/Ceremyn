"""Broker routing for OMS order plans."""

from collections.abc import Mapping

from alphaquant.oms.broker import BrokerAdapter
from alphaquant.oms.exceptions import OMSBrokerCapabilityError, OMSValidationError
from alphaquant.oms.orders import OMSOrder, PlanOrderRole

_BRACKET_ROLES = frozenset({PlanOrderRole.TAKE_PROFIT, PlanOrderRole.STOP_LOSS})


class BrokerRouter:
    def __init__(self, brokers: Mapping[str, BrokerAdapter], default_broker: str) -> None:
        if default_broker not in brokers:
            raise OMSValidationError(f"default broker {default_broker!r} is not configured")
        self._brokers = dict(brokers)
        self._default_broker = default_broker

    @property
    def brokers(self) -> tuple[BrokerAdapter, ...]:
        return tuple(self._brokers.values())

    def route(self, oms_order: OMSOrder) -> BrokerAdapter:
        broker = self._brokers[self._default_broker]
        if oms_order.role in _BRACKET_ROLES and not broker.capabilities.supports_brackets:
            raise OMSBrokerCapabilityError(
                f"broker {broker.name} does not support bracket child orders"
            )
        return broker

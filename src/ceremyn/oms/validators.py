"""OMS validators."""

from ceremyn.domain import OrderType
from ceremyn.oms.broker import BrokerCapabilities
from ceremyn.oms.exceptions import (
    OMSBrokerCapabilityError,
    OMSKillSwitchActiveError,
    OMSValidationError,
)
from ceremyn.oms.orders import OrderIntent, OrderPlan, ReplaceOrderCommand, SubmitOrderCommand


class OMSValidator:
    def validate_intent(self, intent: OrderIntent) -> None:
        if not intent.signal.legs:
            raise OMSValidationError("intent must contain at least one leg")

    def validate_plan(self, plan: OrderPlan) -> None:
        if not plan.orders:
            raise OMSValidationError("plan must contain at least one planned order")

    def validate_submit(
        self,
        command: SubmitOrderCommand,
        capabilities: BrokerCapabilities,
        *,
        kill_switch_armed: bool,
    ) -> None:
        if kill_switch_armed:
            raise OMSKillSwitchActiveError("OMS kill switch is armed")
        order = command.order
        if order.order_type is OrderType.SL_MARKET and not capabilities.supports_stop:
            raise OMSBrokerCapabilityError("broker does not support stop orders")
        if order.order_type is OrderType.SL_LIMIT and not capabilities.supports_stop_limit:
            raise OMSBrokerCapabilityError("broker does not support stop-limit orders")

    def validate_replace(
        self,
        command: ReplaceOrderCommand,
        capabilities: BrokerCapabilities,
        *,
        kill_switch_armed: bool,
    ) -> None:
        if kill_switch_armed:
            raise OMSKillSwitchActiveError("OMS kill switch is armed")
        if not capabilities.supports_replace:
            raise OMSBrokerCapabilityError("broker does not support replace")
        if command.new_limit_price is None and command.new_trigger_price is None:
            raise OMSValidationError("replace requires a new limit or trigger price")

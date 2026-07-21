"""OMS execution-state reducer."""

from decimal import Decimal

from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.exceptions import OMSStateError
from ceremyn.oms.orders import OMSExecutionState, OMSOrder

VALID_EVENT_TRANSITIONS: dict[OMSExecutionState, frozenset[OMSEventType]] = {
    OMSExecutionState.NEW: frozenset(
        {
            OMSEventType.ORDER_VALIDATED,
            OMSEventType.ORDER_ROUTED,
            OMSEventType.FAILED,
            OMSEventType.REJECTED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.VALIDATED: frozenset(
        {
            OMSEventType.ORDER_ROUTED,
            OMSEventType.FAILED,
            OMSEventType.REJECTED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.ROUTED: frozenset(
        {
            OMSEventType.SUBMIT_REQUESTED,
            OMSEventType.ACKNOWLEDGED,
            OMSEventType.CANCEL_REQUESTED,
            OMSEventType.RETRY_SCHEDULED,
            OMSEventType.RETRY_SUCCEEDED,
            OMSEventType.FAILED,
            OMSEventType.EXPIRED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.PENDING: frozenset(
        {
            OMSEventType.PARTIAL_FILL_RECORDED,
            OMSEventType.FILL_RECORDED,
            OMSEventType.CANCEL_REQUESTED,
            OMSEventType.CANCELLED,
            OMSEventType.REPLACED,
            OMSEventType.REJECTED,
            OMSEventType.FAILED,
            OMSEventType.EXPIRED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.PARTIALLY_FILLED: frozenset(
        {
            OMSEventType.PARTIAL_FILL_RECORDED,
            OMSEventType.FILL_RECORDED,
            OMSEventType.CANCEL_REQUESTED,
            OMSEventType.CANCELLED,
            OMSEventType.REPLACED,
            OMSEventType.FAILED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.CANCEL_PENDING: frozenset(
        {
            OMSEventType.CANCELLED,
            OMSEventType.PARTIAL_FILL_RECORDED,
            OMSEventType.FILL_RECORDED,
            OMSEventType.FAILED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.CANCELLED: frozenset({OMSEventType.DUPLICATE_SUPPRESSED}),
    OMSExecutionState.FILLED: frozenset({OMSEventType.DUPLICATE_SUPPRESSED}),
    OMSExecutionState.REJECTED: frozenset({OMSEventType.DUPLICATE_SUPPRESSED}),
    OMSExecutionState.FAILED: frozenset(
        {
            OMSEventType.RETRY_SCHEDULED,
            OMSEventType.RETRY_SUCCEEDED,
            OMSEventType.ACKNOWLEDGED,
            OMSEventType.DUPLICATE_SUPPRESSED,
        }
    ),
    OMSExecutionState.EXPIRED: frozenset({OMSEventType.DUPLICATE_SUPPRESSED}),
}


def reduce_order(order: OMSOrder, event: OMSEvent) -> OMSOrder:
    if event.event_type not in VALID_EVENT_TRANSITIONS[order.execution_state]:
        raise OMSStateError(
            f"illegal OMS event {event.event_type} from state {order.execution_state}"
        )
    state = _next_state(order.execution_state, event.event_type)
    filled_quantity = order.filled_quantity
    average_fill_price = order.average_fill_price
    external_order_id = order.external_order_id
    broker_name = order.broker_name
    retry_count = order.retry_count
    duplicate_count = order.duplicate_count
    last_error = order.last_error
    payload = event.payload

    if event.event_type in {OMSEventType.PARTIAL_FILL_RECORDED, OMSEventType.FILL_RECORDED}:
        quantity = int(payload["quantity"])
        price = Decimal(str(payload["price"]))
        prior_notional = (
            (average_fill_price or Decimal("0")) * filled_quantity
            if average_fill_price
            else Decimal("0")
        )
        filled_quantity += quantity
        average_fill_price = (prior_notional + price * quantity) / filled_quantity

    if event.event_type is OMSEventType.ACKNOWLEDGED:
        external_order_id = str(payload["external_order_id"])
        broker_name = str(payload["broker_name"])
        last_error = ""
    elif event.event_type is OMSEventType.FAILED or event.event_type is OMSEventType.REJECTED:
        last_error = str(payload.get("reason", ""))
    elif event.event_type is OMSEventType.RETRY_SCHEDULED:
        retry_count += 1
        last_error = str(payload.get("reason", ""))
    elif event.event_type is OMSEventType.DUPLICATE_SUPPRESSED:
        duplicate_count += 1
    elif event.event_type is OMSEventType.RETRY_SUCCEEDED:
        last_error = ""

    return order.model_copy(
        update={
            "execution_state": state,
            "filled_quantity": filled_quantity,
            "average_fill_price": average_fill_price,
            "external_order_id": external_order_id,
            "broker_name": broker_name,
            "retry_count": retry_count,
            "duplicate_count": duplicate_count,
            "last_error": last_error,
            "event_log": (*order.event_log, event),
            "updated_at": event.occurred_at,
        }
    )


def _next_state(state: OMSExecutionState, event_type: OMSEventType) -> OMSExecutionState:
    if event_type is OMSEventType.ORDER_VALIDATED:
        return OMSExecutionState.VALIDATED
    if event_type is OMSEventType.ORDER_ROUTED:
        return OMSExecutionState.ROUTED
    if event_type is OMSEventType.SUBMIT_REQUESTED:
        return OMSExecutionState.ROUTED
    if event_type is OMSEventType.ACKNOWLEDGED:
        return OMSExecutionState.PENDING
    if event_type is OMSEventType.PARTIAL_FILL_RECORDED:
        return OMSExecutionState.PARTIALLY_FILLED
    if event_type is OMSEventType.FILL_RECORDED:
        return OMSExecutionState.FILLED
    if event_type is OMSEventType.CANCEL_REQUESTED:
        return OMSExecutionState.CANCEL_PENDING
    if event_type is OMSEventType.CANCELLED:
        return OMSExecutionState.CANCELLED
    if event_type is OMSEventType.REPLACED:
        return OMSExecutionState.PENDING
    if event_type is OMSEventType.REJECTED:
        return OMSExecutionState.REJECTED
    if event_type is OMSEventType.FAILED:
        return OMSExecutionState.FAILED
    if event_type is OMSEventType.EXPIRED:
        return OMSExecutionState.EXPIRED
    return state

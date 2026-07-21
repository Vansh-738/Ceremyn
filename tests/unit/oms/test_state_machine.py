import pytest

from ceremyn.oms import OMSEvent, OMSEventType, OMSExecutionState
from ceremyn.oms.exceptions import OMSStateError
from tests.unit.oms.conftest import T0
from tests.unit.oms.test_support import make_oms_order


def routed_order():
    order = make_oms_order()
    return order.with_event(
        OMSEvent(
            event_type=OMSEventType.ORDER_VALIDATED,
            oms_order_id=order.oms_order_id,
            occurred_at=T0,
        )
    ).with_event(
        OMSEvent(
            event_type=OMSEventType.ORDER_ROUTED,
            oms_order_id=order.oms_order_id,
            occurred_at=T0,
        )
    )


def test_state_machine_happy_path() -> None:
    order = routed_order()
    order = order.with_event(
        OMSEvent(
            event_type=OMSEventType.ACKNOWLEDGED,
            oms_order_id=order.oms_order_id,
            occurred_at=T0,
            payload={"external_order_id": "ext-1", "broker_name": "fake"},
        )
    )
    order = order.with_event(
        OMSEvent(
            event_type=OMSEventType.FILL_RECORDED,
            oms_order_id=order.oms_order_id,
            occurred_at=T0,
            payload={"quantity": 75, "price": "150"},
        )
    )

    assert order.execution_state is OMSExecutionState.FILLED
    assert order.filled_quantity == 75


def test_illegal_transition_raises() -> None:
    order = routed_order()
    with pytest.raises(OMSStateError):
        order.with_event(
            OMSEvent(
                event_type=OMSEventType.FILL_RECORDED,
                oms_order_id=order.oms_order_id,
                occurred_at=T0,
                payload={"quantity": 75, "price": "150"},
            )
        )

from datetime import timedelta
from decimal import Decimal

import pytest

from ceremyn.oms import (
    BrokerExecutor,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerSubmissionResult,
    RetryPolicy,
)
from ceremyn.oms.exceptions import OMSNonRetryableBrokerError
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand
from tests.unit.oms.conftest import T0, FakeBroker
from tests.unit.oms.test_support import make_oms_order


class FatalBroker(FakeBroker):
    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        raise OMSNonRetryableBrokerError("fatal")


class LookupBroker(FakeBroker):
    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        raise RuntimeError("ambiguous")

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None:
        return next(iter(self.orders.values()))


def test_executor_lookup_cancel_replace_and_nonretryable_branch() -> None:
    order = make_oms_order()
    submit = SubmitOrderCommand(
        oms_order_id=order.oms_order_id,
        strategy_id=order.strategy_id,
        broker_name="fake",
        request_hash=order.request_hash,
        order=order.order,
        requested_at=T0,
    )

    broker = LookupBroker()
    external_order_id = f"ext-{order.oms_order_id}"
    broker.orders[external_order_id] = BrokerOrderSnapshot(
        external_order_id=external_order_id,
        status=BrokerOrderStatus.ACKNOWLEDGED,
        broker_timestamp=T0,
        filled_quantity=0,
        remaining_quantity=order.order.quantity,
        correlation_id=str(submit.correlation_id) if submit.correlation_id else None,
        request_hash=order.request_hash,
    )
    result = BrokerExecutor(RetryPolicy()).submit(broker, order, submit)
    assert result.submission is not None

    cancel = BrokerExecutor(RetryPolicy()).cancel(
        broker,
        CancelOrderCommand(
            oms_order_id=order.oms_order_id,
            external_order_id=result.submission.external_order_id,
            broker_name="fake",
            requested_at=T0 + timedelta(seconds=1),
        ),
    )
    assert cancel.cancel is not None

    replace = BrokerExecutor(RetryPolicy()).replace(
        broker,
        ReplaceOrderCommand(
            oms_order_id=order.oms_order_id,
            external_order_id=result.submission.external_order_id,
            broker_name="fake",
            requested_at=T0 + timedelta(seconds=2),
            new_limit_price=Decimal("101"),
        ),
    )
    assert replace.replace is not None

    with pytest.raises(OMSNonRetryableBrokerError):
        BrokerExecutor(RetryPolicy()).submit(FatalBroker(), order, submit)

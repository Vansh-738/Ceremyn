from datetime import timedelta
from decimal import Decimal

import pytest

from alphaquant.oms import (
    BrokerCapabilities,
    BrokerExecutionReport,
    BrokerOrderStatus,
    OMSDuplicateRequestError,
    OMSExecutionState,
    OMSKillSwitchActiveError,
    OrderManagementEngine,
)
from alphaquant.risk import RiskEngine
from tests.unit.oms.conftest import T0, FakeBroker, make_signal


def make_engine(
    risk_engine: RiskEngine,
    broker: FakeBroker | None = None,
) -> OrderManagementEngine:
    return OrderManagementEngine(
        risk_engine=risk_engine,
        brokers={"fake": broker or FakeBroker()},
        default_broker="fake",
    )


def test_submit_signal_and_fill_flow(risk_engine: RiskEngine) -> None:
    broker = FakeBroker()
    engine = make_engine(risk_engine, broker)

    orders = engine.submit_signal(make_signal(), now=T0)

    assert len(orders) == 1
    assert orders[0].execution_state is OMSExecutionState.PENDING
    external_order_id = orders[0].external_order_id
    assert external_order_id is not None

    updated = engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=external_order_id,
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="fill-1",
            last_fill_quantity=75,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )

    assert updated.execution_state is OMSExecutionState.FILLED
    assert engine.portfolio.positions[updated.order.contract.tradingsymbol].quantity == 75


def test_kill_switch_blocks_new_submissions_but_not_cancel(
    risk_engine: RiskEngine,
) -> None:
    broker = FakeBroker()
    engine = make_engine(risk_engine, broker)
    (order,) = engine.submit_signal(make_signal(), now=T0)
    engine.arm_kill_switch("manual", at=T0)

    with pytest.raises(OMSKillSwitchActiveError):
        engine.submit_signal(make_signal(correlation_id=None), now=T0 + timedelta(seconds=1))

    cancelled = engine.cancel_order(
        order.oms_order_id, reason="flatten", now=T0 + timedelta(seconds=2)
    )
    assert cancelled.execution_state is OMSExecutionState.CANCELLED


def test_duplicate_submission_is_suppressed(risk_engine: RiskEngine) -> None:
    broker = FakeBroker()
    engine = make_engine(risk_engine, broker)
    signal = make_signal()
    engine.submit_signal(signal, now=T0)
    with pytest.raises(OMSDuplicateRequestError):
        engine.submit_signal(signal, now=T0)


def test_retryable_submit_eventually_succeeds(risk_engine: RiskEngine) -> None:
    broker = FakeBroker(fail_first_submit=True)
    engine = make_engine(risk_engine, broker)

    (order,) = engine.submit_signal(make_signal(), now=T0)

    assert order.execution_state is OMSExecutionState.PENDING
    assert order.retry_count == 1
    assert engine.metrics.retry_count == 1


def test_bracket_children_activate_and_replace_and_reconcile(risk_engine: RiskEngine) -> None:
    broker = FakeBroker(
        capabilities=BrokerCapabilities(supports_replace=True, supports_brackets=True)
    )
    engine = make_engine(risk_engine, broker)

    orders = engine.submit_signal(make_signal(style="bracket"), now=T0)
    entry = next(order for order in orders if order.role.value == "entry")
    children = [order for order in orders if order.parent_order_id == entry.order.id]
    assert all(child.execution_state is OMSExecutionState.ROUTED for child in children)

    engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=entry.external_order_id or "",
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="entry-fill",
            last_fill_quantity=25,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )
    assert all(
        engine.orders[child.oms_order_id].external_order_id is not None for child in children
    )

    replaced = engine.replace_order(
        children[0].oms_order_id,
        new_limit_price=Decimal("160"),
        now=T0 + timedelta(seconds=2),
    )
    assert replaced.execution_state is OMSExecutionState.PENDING

    engine.disarm_kill_switch(at=T0 + timedelta(seconds=3))
    report = engine.reconcile(now=T0 + timedelta(seconds=4))
    assert report is not None
    assert engine.metrics_snapshot(now=T0 + timedelta(seconds=4)).orders_submitted >= 1


def test_bracket_children_fail_to_activate_when_kill_switch_armed(risk_engine: RiskEngine) -> None:
    broker = FakeBroker()
    engine = make_engine(risk_engine, broker)
    orders = engine.submit_signal(make_signal(style="bracket"), now=T0)
    entry = next(order for order in orders if order.role.value == "entry")
    child = next(order for order in orders if order.parent_order_id == entry.order.id)
    engine.arm_kill_switch("panic", at=T0)

    engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=entry.external_order_id or "",
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="entry-fill-2",
            last_fill_quantity=25,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )
    assert engine.orders[child.oms_order_id].execution_state is OMSExecutionState.FAILED

from datetime import timedelta
from decimal import Decimal

import pytest

from ceremyn.domain import OrderType
from ceremyn.oms import (
    BrokerCapabilities,
    BrokerExecutionReport,
    BrokerOrderStatus,
    FillProcessor,
    OMSEvent,
    OMSEventType,
    OMSExecutionState,
    OMSJournal,
    OMSMetrics,
    OMSPortfolio,
    OMSReconciler,
    OMSValidator,
)
from ceremyn.oms.exceptions import (
    OMSBrokerCapabilityError,
    OMSKillSwitchActiveError,
    OMSValidationError,
)
from ceremyn.oms.ledger import OMSLedger
from ceremyn.oms.orders import OMSOrder, PlanOrderRole, ReplaceOrderCommand, SubmitOrderCommand
from ceremyn.oms.router import BrokerRouter
from tests.unit.oms.conftest import T0, FakeBroker, make_signal
from tests.unit.oms.test_support import make_oms_order


def _acknowledged_order() -> OMSOrder:
    order = make_oms_order()
    return (
        order.with_event(
            OMSEvent(
                event_type=OMSEventType.ORDER_VALIDATED,
                oms_order_id=order.oms_order_id,
                occurred_at=T0,
            )
        )
        .with_event(
            OMSEvent(
                event_type=OMSEventType.ORDER_ROUTED,
                oms_order_id=order.oms_order_id,
                occurred_at=T0,
            )
        )
        .with_event(
            OMSEvent(
                event_type=OMSEventType.ACKNOWLEDGED,
                oms_order_id=order.oms_order_id,
                occurred_at=T0,
                payload={"external_order_id": "ext-1", "broker_name": "fake"},
            )
        )
    )


def test_fill_processor_handles_duplicates_and_terminal_reports() -> None:
    order = _acknowledged_order()
    processor = FillProcessor()
    updated, fill, duplicate = processor.process(
        order,
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.PARTIALLY_FILLED,
            broker_timestamp=T0,
            fill_id="fill-1",
            last_fill_quantity=25,
            fill_price=Decimal("100"),
            remaining_quantity=50,
        ),
    )
    assert duplicate is False
    assert fill is not None
    assert updated.execution_state is OMSExecutionState.PARTIALLY_FILLED

    duplicate_order, duplicate_fill, duplicate_seen = processor.process(
        updated,
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.PARTIALLY_FILLED,
            broker_timestamp=T0,
            fill_id="fill-1",
            last_fill_quantity=25,
            fill_price=Decimal("100"),
            remaining_quantity=50,
        ),
    )
    assert duplicate_seen is True
    assert duplicate_fill is None
    assert duplicate_order.duplicate_count == 1

    cancelled, _, _ = processor.process(
        updated,
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.CANCELLED,
            broker_timestamp=T0 + timedelta(seconds=1),
        ),
    )
    assert cancelled.execution_state is OMSExecutionState.CANCELLED

    rejected, _, _ = processor.process(
        _acknowledged_order(),
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.REJECTED,
            broker_timestamp=T0 + timedelta(seconds=1),
            message="bad",
        ),
    )
    assert rejected.execution_state is OMSExecutionState.REJECTED

    failed, _, _ = processor.process(
        _acknowledged_order(),
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.FAILED,
            broker_timestamp=T0 + timedelta(seconds=1),
            message="oops",
        ),
    )
    assert failed.execution_state is OMSExecutionState.FAILED

    expired, _, _ = processor.process(
        _acknowledged_order(),
        BrokerExecutionReport(
            external_order_id="ext-1",
            status=BrokerOrderStatus.EXPIRED,
            broker_timestamp=T0 + timedelta(seconds=1),
        ),
    )
    assert expired.execution_state is OMSExecutionState.EXPIRED


def test_journal_json_store_metrics_positions_and_reconcile(tmp_path) -> None:
    journal = OMSJournal("session", store=None)
    signal = make_signal()
    journal.record_signal(signal, at=T0)
    journal.record_kill_switch(armed=True, reason="manual", at=T0)
    assert len(journal.store.entries()) == 2

    from ceremyn.oms.journal import JSONJournalStore
    from ceremyn.oms.journal import OMSJournal as DurableJournal

    durable = DurableJournal("session", store=JSONJournalStore("session", root=tmp_path))
    durable.record_signal(signal, at=T0)
    assert len(durable.store.entries()) == 1

    metrics = OMSMetrics()
    metrics.record_submission(0.1, broker_latency_seconds=0.05)
    metrics.record_submission(0.2, broker_latency_seconds=0.10)
    metrics.record_fill(partial=True)
    metrics.record_fill(partial=False)
    metrics.record_rejection()
    metrics.record_retry(success=False)
    metrics.record_retry(success=True)
    metrics.record_duplicate()
    metrics.record_broker_health(success=True)
    metrics.record_broker_health(success=False)
    snapshot = metrics.snapshot(T0)
    assert snapshot.p95_latency_seconds >= 0.1
    assert snapshot.p99_latency_seconds >= snapshot.p95_latency_seconds
    assert snapshot.retry_success_rate == 0.5
    assert snapshot.broker_uptime_ratio == 0.5

    portfolio = OMSPortfolio()
    marked = portfolio.mark(
        timestamp=T0,
        last_prices={"NIFTY25JUL25000CE": Decimal("150")},
        pending_orders=(),
    )
    assert marked.buying_power > 0
    assert portfolio.session_statistics().total_return == 0

    broker = FakeBroker()
    ledger = OMSLedger()
    report = OMSReconciler().reconcile(orders=(), broker=broker, ledger=ledger, portfolio=portfolio)
    assert report.reconciled is True


def test_order_snapshot_round_trips_through_journal(tmp_path) -> None:
    from ceremyn.oms.journal import JSONJournalStore
    from ceremyn.oms.restore import rebuild_oms_state

    store = JSONJournalStore("session", root=tmp_path)
    journal = OMSJournal("session", store=store)

    parent = make_oms_order()
    child = make_oms_order().model_copy(
        update={"parent_order_id": parent.oms_order_id, "request_hash": "child-hash"}
    )
    # A later snapshot for the same order supersedes the earlier one (append-only log).
    journal.record_order_snapshot(parent, at=T0)
    updated_parent = parent.model_copy(update={"external_order_id": "ext-parent-final"})
    journal.record_order_snapshot(updated_parent, at=T0)
    journal.record_order_snapshot(child, at=T0)

    state = rebuild_oms_state(store)
    assert set(state.orders) == {parent.oms_order_id, child.oms_order_id}
    assert state.orders[parent.oms_order_id].external_order_id == "ext-parent-final"
    assert state.external_index["ext-parent-final"] == parent.oms_order_id
    assert state.children[parent.oms_order_id] == [child.oms_order_id]
    assert (parent.request_hash, parent.oms_order_id) in state.idempotency_seed


def test_validators_and_router_guard_capabilities() -> None:
    validator = OMSValidator()
    order = make_oms_order()
    submit = SubmitOrderCommand(
        oms_order_id=order.oms_order_id,
        strategy_id=order.strategy_id,
        broker_name="fake",
        request_hash=order.request_hash,
        order=order.order.model_copy(
            update={"order_type": OrderType.SL_MARKET, "trigger_price": Decimal("100")}
        ),
    )
    with pytest.raises(OMSBrokerCapabilityError):
        validator.validate_submit(
            submit,
            BrokerCapabilities(supports_stop=False),
            kill_switch_armed=False,
        )
    with pytest.raises(OMSKillSwitchActiveError):
        validator.validate_submit(
            submit,
            BrokerCapabilities(),
            kill_switch_armed=True,
        )
    replace = ReplaceOrderCommand(
        oms_order_id=order.oms_order_id,
        broker_name="fake",
    )
    with pytest.raises(OMSValidationError):
        validator.validate_replace(
            replace,
            BrokerCapabilities(supports_replace=True),
            kill_switch_armed=False,
        )
    with pytest.raises(OMSBrokerCapabilityError):
        validator.validate_replace(
            replace.model_copy(update={"new_limit_price": Decimal("100")}),
            BrokerCapabilities(supports_replace=False),
            kill_switch_armed=False,
        )


def test_router_only_gates_bracket_roles_on_supports_brackets() -> None:
    """Regression: `route()` used to raise for *any* non-ENTRY role (including the new
    COMPENSATION role) whenever `supports_brackets` was False — a compensation order has
    nothing to do with bracket children and must route like a normal ENTRY order."""
    broker = FakeBroker(capabilities=BrokerCapabilities(supports_brackets=False))
    router = BrokerRouter({"only": broker}, default_broker="only")
    entry_order = make_oms_order()
    assert router.route(entry_order) is broker

    compensation_order = entry_order.model_copy(update={"role": PlanOrderRole.COMPENSATION})
    assert router.route(compensation_order) is broker

    take_profit_order = entry_order.model_copy(update={"role": PlanOrderRole.TAKE_PROFIT})
    with pytest.raises(OMSBrokerCapabilityError):
        router.route(take_profit_order)

    stop_loss_order = entry_order.model_copy(update={"role": PlanOrderRole.STOP_LOSS})
    with pytest.raises(OMSBrokerCapabilityError):
        router.route(stop_loss_order)

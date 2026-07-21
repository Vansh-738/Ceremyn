from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphaquant.domain import Side, SignalLeg
from alphaquant.oms import (
    BrokerCapabilities,
    BrokerExecutionReport,
    BrokerOrderStatus,
    JSONJournalStore,
    OMSDuplicateRequestError,
    OMSExecutionState,
    OMSJournal,
    OMSKillSwitchActiveError,
    OrderManagementEngine,
    PlanOrderRole,
)
from alphaquant.oms.compensation import compensate_siblings
from alphaquant.risk import RiskDecision, RiskEngine
from tests.unit.oms.conftest import T0, FakeBroker, make_multi_leg_signal, make_signal


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


def test_multi_leg_signal_compensates_siblings_when_one_leg_is_rejected(
    risk_engine: RiskEngine,
) -> None:
    signal = make_multi_leg_signal(legs=4)
    rejected_symbol = signal.legs[2].contract.tradingsymbol
    broker = FakeBroker(reject_tradingsymbols=frozenset({rejected_symbol}))
    engine = make_engine(risk_engine, broker)

    orders = engine.submit_signal(signal, now=T0)

    rejected_leg = next(o for o in orders if o.order.contract.tradingsymbol == rejected_symbol)
    assert rejected_leg.execution_state is OMSExecutionState.FAILED

    surviving_legs = [o for o in orders if o.order.contract.tradingsymbol != rejected_symbol]
    assert len(surviving_legs) == 3
    # Every surviving leg was still resting (unfilled) when the rejection landed, so
    # compensation cancels each one outright rather than submitting a closing order.
    for leg in surviving_legs:
        assert engine.orders[leg.oms_order_id].execution_state is OMSExecutionState.CANCELLED


def test_submit_correlated_signals_compensates_across_signals_on_risk_rejection(
    risk_engine: RiskEngine,
) -> None:
    """Calendar-Spread-shaped: two single-leg signals sharing a correlation_id, the
    second rejected by risk after the first is already live -- the first must be
    unwound rather than left as a naked leg."""

    class RejectSecondSignal(RiskEngine):
        def __init__(self, settings: object) -> None:
            super().__init__(settings)  # type: ignore[arg-type]
            self.calls = 0

        def validate(self, portfolio, signal, *, evaluated_at=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 2:
                return RiskDecision(
                    approved=False,
                    risk_score=0.0,
                    violations=["test: reject second leg"],
                    timestamp=evaluated_at or T0,
                )
            return super().validate(portfolio, signal, evaluated_at=evaluated_at)

    from tests.unit.oms.conftest import permissive_settings

    correlation_id = uuid4()
    near_leg = make_signal(correlation_id=correlation_id)
    far_leg = make_signal(correlation_id=correlation_id)
    broker = FakeBroker()
    engine = make_engine(RejectSecondSignal(permissive_settings()), broker)

    orders = engine.submit_correlated_signals([near_leg, far_leg], now=T0)

    entries = [o for o in orders if o.role is PlanOrderRole.ENTRY]
    assert len(entries) == 1  # only the first signal's leg was ever accepted
    # It was still resting (unfilled) when its sibling was rejected, so it gets
    # cancelled rather than closed with an offsetting order.
    assert engine.orders[entries[0].oms_order_id].execution_state is OMSExecutionState.CANCELLED


def test_bypass_kill_switch_lets_a_filled_leg_be_flattened_while_new_orders_stay_blocked(
    risk_engine: RiskEngine,
) -> None:
    """Once a leg has actually filled, compensating it means submitting a real
    offsetting order — and that must go through even if something (e.g. an automatic
    drawdown trip) has since armed the kill switch, while genuinely new signals stay
    blocked as normal."""
    broker = FakeBroker()
    engine = make_engine(risk_engine, broker)
    (order,) = engine.submit_signal(make_signal(), now=T0)
    filled = engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=order.external_order_id or "",
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="fill-1",
            last_fill_quantity=order.order.quantity,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )
    assert filled.execution_state is OMSExecutionState.FILLED

    engine.arm_kill_switch("automatic drawdown trip", at=T0 + timedelta(seconds=2))
    compensate_siblings(engine, [filled], at=T0 + timedelta(seconds=3))

    compensations = [o for o in engine.orders.values() if o.role is PlanOrderRole.COMPENSATION]
    assert len(compensations) == 1
    assert compensations[0].parent_order_id == filled.oms_order_id
    assert compensations[0].execution_state in {
        OMSExecutionState.PENDING,
        OMSExecutionState.FILLED,
    }

    # A brand new signal is still correctly blocked -- the bypass is scoped to
    # compensation only, never a general kill-switch override.
    with pytest.raises(OMSKillSwitchActiveError):
        engine.submit_signal(make_signal(correlation_id=None), now=T0 + timedelta(seconds=4))


def test_restore_from_journal_rebuilds_state_across_engine_instances(
    risk_engine: RiskEngine, tmp_path
) -> None:
    store = JSONJournalStore("restart-session", root=tmp_path)
    journal_a = OMSJournal("restart-session", store=store)
    broker = FakeBroker()
    engine_a = OrderManagementEngine(
        risk_engine=risk_engine,
        brokers={"fake": broker},
        default_broker="fake",
        journal=journal_a,
    )
    signal = make_signal()
    (order,) = engine_a.submit_signal(signal, now=T0)

    store_b = JSONJournalStore("restart-session", root=tmp_path)
    journal_b = OMSJournal("restart-session", store=store_b)
    engine_b = OrderManagementEngine(
        risk_engine=risk_engine,
        brokers={"fake": FakeBroker()},
        default_broker="fake",
        journal=journal_b,
    )
    engine_b.restore_from_journal()

    assert order.oms_order_id in engine_b.orders
    assert engine_b.orders[order.oms_order_id].request_hash == order.request_hash
    if order.external_order_id is not None:
        assert engine_b.external_index[order.external_order_id] == order.oms_order_id
    # The idempotency reservation is restored too: resubmitting the *same* signal
    # (same signal_id, hence same request_hash) against the "restarted" engine is
    # suppressed rather than duplicated.
    with pytest.raises(OMSDuplicateRequestError):
        engine_b.submit_signal(signal, now=T0)


def test_restore_from_journal_replays_fills_into_portfolio(
    risk_engine: RiskEngine, tmp_path
) -> None:
    """A restart must not just remember order metadata -- it must also reconstruct
    cash/positions/realized_pnl from the fills that already happened, or a real
    account's trading history silently vanishes every time the process restarts even
    though the fills themselves were durably journaled all along."""
    store = JSONJournalStore("restart-fills", root=tmp_path)
    journal_a = OMSJournal("restart-fills", store=store)
    broker = FakeBroker()
    engine_a = OrderManagementEngine(
        risk_engine=risk_engine,
        brokers={"fake": broker},
        default_broker="fake",
        journal=journal_a,
    )
    (order,) = engine_a.submit_signal(make_signal(), now=T0)
    assert order.external_order_id is not None
    filled = engine_a.process_execution_report(
        BrokerExecutionReport(
            external_order_id=order.external_order_id,
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="fill-1",
            last_fill_quantity=order.order.quantity,
            fill_price=Decimal("150"),
            remaining_quantity=0,
        )
    )
    symbol = filled.order.contract.tradingsymbol
    assert engine_a.portfolio.positions[symbol].quantity == order.order.quantity

    # Close it out at a different price so a real, non-zero realized_pnl exists --
    # `snapshot()` is a *cached* view, only refreshed by `mark()`; a naive restore
    # that replays fills via `apply_fill` alone but never calls `mark()` leaves
    # `snapshot()` returning the empty-account default forever, even though cash and
    # positions (live properties, not cached) already reflect the real fills.
    close_signal = make_signal(correlation_id=None)
    close_signal = close_signal.model_copy(
        update={"legs": (SignalLeg(contract=order.order.contract, side=Side.SELL, lots=1),)}
    )
    (close_order,) = engine_a.submit_signal(close_signal, now=T0 + timedelta(seconds=2))
    assert close_order.external_order_id is not None
    engine_a.process_execution_report(
        BrokerExecutionReport(
            external_order_id=close_order.external_order_id,
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=3),
            fill_id="fill-2",
            last_fill_quantity=close_order.order.quantity,
            fill_price=Decimal("200"),
            remaining_quantity=0,
        )
    )
    # `snapshot()` is cached, only refreshed by `mark()` -- mimic what a real runner
    # (e.g. `RestPricePoller`) does on its next tick, to get an honest ground truth.
    engine_a.portfolio.mark(timestamp=T0 + timedelta(seconds=3), last_prices={})
    expected_realized_pnl = engine_a.portfolio.snapshot().realized_pnl
    assert expected_realized_pnl != 0
    expected_cash = engine_a.portfolio.cash

    store_b = JSONJournalStore("restart-fills", root=tmp_path)
    journal_b = OMSJournal("restart-fills", store=store_b)
    engine_b = OrderManagementEngine(
        risk_engine=risk_engine,
        brokers={"fake": FakeBroker()},
        default_broker="fake",
        journal=journal_b,
    )
    engine_b.restore_from_journal()

    assert engine_b.portfolio.cash == expected_cash
    assert engine_b.portfolio.snapshot().realized_pnl == expected_realized_pnl

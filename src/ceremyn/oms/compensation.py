"""Compensation planning and execution for partially-accepted multi-leg orders.

When some legs of a multi-leg order (a single `Signal`'s multiple `SignalLeg`s, or a
`correlation_id` group of separately-submitted signals such as Calendar Spread's paired
near/far legs) end up rejected or failed while sibling legs already reached a live or
filled state, the position must not be left partial.

`plan_compensation`/`needs_compensation` are pure and side-effect-free. The rest of this
module (`submit_correlated_signals`, `compensate_siblings`, ...) executes those plans
against a live `OrderManagementEngine` — split out of `oms/engine.py` purely to keep
that file under the project's line-count convention; `OrderManagementEngine`'s own
`submit_signal`/`submit_correlated_signals` methods are thin delegates to functions here.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from ceremyn.core.timeutils import now_utc
from ceremyn.domain import Order, OrderType, Side, Signal
from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.exceptions import (
    OMSDuplicateRequestError,
    OMSKillSwitchActiveError,
    OMSNonRetryableBrokerError,
    OMSRiskRejectedError,
)
from ceremyn.oms.orders import (
    OMSExecutionState,
    OMSOrder,
    OrderPlan,
    PlannedOrder,
    PlanOrderRole,
)

if TYPE_CHECKING:
    from ceremyn.oms.engine import OrderManagementEngine

logger = structlog.get_logger(__name__)

LIVE_OR_FILLED_STATES = frozenset(
    {
        OMSExecutionState.PENDING,
        OMSExecutionState.PARTIALLY_FILLED,
        OMSExecutionState.FILLED,
    }
)

BAD_TERMINAL_STATES = frozenset({OMSExecutionState.REJECTED, OMSExecutionState.FAILED})


class CompensationAction(StrEnum):
    CANCEL = "cancel"
    CLOSE = "close"


@dataclass(frozen=True)
class CompensationPlan:
    action: CompensationAction
    sibling: OMSOrder
    closing_order: Order | None = None


def needs_compensation(orders: list[OMSOrder]) -> bool:
    """True iff `orders` mixes a bad-terminal leg with a live/filled sibling."""
    states = {order.execution_state for order in orders}
    return bool(states & BAD_TERMINAL_STATES) and bool(states & LIVE_OR_FILLED_STATES)


def plan_compensation(siblings: list[OMSOrder], *, at: datetime) -> tuple[CompensationPlan, ...]:
    """Decide how to unwind each still-live/filled sibling.

    Resting, unfilled orders are cancelled outright. Anything with a fill already
    booked is closed with an opposite-side market order for the filled quantity —
    the safest immediate flatten, since it needs no limit/trigger price.
    """
    plans: list[CompensationPlan] = []
    for sibling in siblings:
        if sibling.execution_state not in LIVE_OR_FILLED_STATES:
            continue
        if sibling.filled_quantity > 0:
            plans.append(
                CompensationPlan(
                    action=CompensationAction.CLOSE,
                    sibling=sibling,
                    closing_order=_closing_order(sibling, at=at),
                )
            )
        else:
            plans.append(CompensationPlan(action=CompensationAction.CANCEL, sibling=sibling))
    return tuple(plans)


def _closing_order(sibling: OMSOrder, *, at: datetime) -> Order:
    original = sibling.order
    opposite_side = Side.SELL if original.side is Side.BUY else Side.BUY
    return Order(
        signal_id=original.signal_id,
        contract=original.contract,
        side=opposite_side,
        quantity=sibling.filled_quantity,
        order_type=OrderType.MARKET,
        product=original.product,
        created_at=at,
    )


# -- execution against a live engine ---------------------------------------------


def mark_submission_failed(
    engine: "OrderManagementEngine", oms_order_id: UUID, *, reason: str, at: datetime
) -> OMSOrder:
    order = engine.orders[oms_order_id]
    failed = order.with_event(
        OMSEvent(
            event_type=OMSEventType.FAILED,
            oms_order_id=order.oms_order_id,
            correlation_id=order.correlation_id,
            occurred_at=at,
            payload={"reason": reason},
        )
    )
    engine._persist_order(failed, at=at)
    engine._record_event(failed.event_log[-1])
    engine.metrics.record_broker_health(success=False)
    return failed


def compensate_siblings(
    engine: "OrderManagementEngine", siblings: Sequence[OMSOrder], *, at: datetime
) -> None:
    for compensation in plan_compensation(list(siblings), at=at):
        if compensation.action is CompensationAction.CANCEL:
            engine.cancel_order(compensation.sibling.oms_order_id, reason="compensation", now=at)
        else:
            assert compensation.closing_order is not None  # CLOSE always sets it
            submit_compensation_order(
                engine, compensation.sibling, compensation.closing_order, at=at
            )


def submit_compensation_order(
    engine: "OrderManagementEngine", sibling: OMSOrder, closing_order: Order, *, at: datetime
) -> OMSOrder | None:
    # Every order the engine builds is signal-driven (see `_build_oms_order`), so a
    # sibling eligible for compensation always carries the signal_id it was built from.
    assert sibling.signal_id is not None
    planned = PlannedOrder(
        role=PlanOrderRole.COMPENSATION,
        order=closing_order,
        parent_order_id=sibling.oms_order_id,
    )
    plan = OrderPlan(
        intent_id=sibling.intent_id,
        strategy_id=sibling.strategy_id,
        signal_id=sibling.signal_id,
        correlation_id=sibling.correlation_id,
        orders=(planned,),
    )
    oms_order = engine._build_oms_order(plan, planned, at=at)
    duplicate = engine.idempotency.reserve(oms_order.request_hash, oms_order.oms_order_id)
    if duplicate is not None:
        # Already compensated (e.g. this sibling was already flattened) — no-op.
        return engine.orders.get(duplicate)
    engine._persist_order(oms_order, at=at)
    engine._record_event(
        OMSEvent(
            event_type=OMSEventType.COMPENSATION_SUBMITTED,
            oms_order_id=oms_order.oms_order_id,
            correlation_id=oms_order.correlation_id,
            occurred_at=at,
            payload={"compensates_oms_order_id": str(sibling.oms_order_id)},
        )
    )
    try:
        return engine._submit_existing_order(oms_order.oms_order_id, at=at, bypass_kill_switch=True)
    except OMSNonRetryableBrokerError as exc:
        return mark_submission_failed(engine, oms_order.oms_order_id, reason=str(exc), at=at)


def submit_correlated_signals(
    engine: "OrderManagementEngine",
    signals: Sequence[Signal],
    *,
    now: datetime | None = None,
) -> tuple[OMSOrder, ...]:
    """Submit every signal from one strategy tick as a cohesive group.

    Most strategies return zero or one `Signal` per tick, so this behaves exactly
    like calling `submit_signal` once. Calendar Spread is the one strategy that
    returns two single-leg signals sharing a `correlation_id` (a cross-expiry
    structure can't live in one `Signal` — see `strategies/calendar_spread.py`);
    if one signal in such a group is rejected/fails while a sibling already reached
    a live or filled state, the sibling is compensated the same way a partially
    accepted multi-leg `Signal` is.
    """
    by_correlation: defaultdict[UUID | None, list[OMSOrder]] = defaultdict(list)
    all_orders: list[OMSOrder] = []
    failed_correlations: set[UUID] = set()
    skip_errors = (OMSRiskRejectedError, OMSDuplicateRequestError, OMSKillSwitchActiveError)
    for signal in signals:
        try:
            orders = engine.submit_signal(signal, now=now)
        except skip_errors as exc:
            # A kill-switch trip (e.g. an automatic risk breach) blocking this signal
            # is exactly when a sibling that already landed most needs unwinding, not
            # an excuse to abandon the group — so this is treated as a rejection too,
            # not left to propagate and skip compensation for the rest of the group.
            logger.warning(
                "correlated_signal_rejected",
                signal_id=str(signal.signal_id),
                correlation_id=str(signal.correlation_id),
                reason=str(exc),
            )
            if signal.correlation_id is not None:
                failed_correlations.add(signal.correlation_id)
            continue
        all_orders.extend(orders)
        if signal.correlation_id is not None:
            by_correlation[signal.correlation_id].extend(orders)
            # A signal can also fail at the broker without submit_signal raising —
            # its own within-plan compensation only fires when it has a live sibling
            # of *its own*; a lone failed leg here still needs to flag its group.
            if any(order.execution_state in BAD_TERMINAL_STATES for order in orders):
                failed_correlations.add(signal.correlation_id)

    timestamp = now or now_utc()
    for correlation_id in failed_correlations:
        siblings = by_correlation.get(correlation_id)
        if siblings:
            compensate_siblings(engine, siblings, at=timestamp)
    return tuple(all_orders)

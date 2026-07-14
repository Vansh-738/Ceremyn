from alphaquant.oms import OMSOrder, OrderPlanner
from tests.unit.oms.conftest import T0, make_signal


def make_oms_order() -> OMSOrder:
    planner = OrderPlanner()
    intent = planner.intent_from_signal(make_signal(), now=T0)
    plan = planner.plan(intent, now=T0)
    return OMSOrder(
        plan_id=plan.plan_id,
        intent_id=plan.intent_id,
        request_hash="abc",
        strategy_id=plan.strategy_id,
        signal_id=plan.signal_id,
        correlation_id=plan.correlation_id,
        order=plan.orders[0].order,
        created_at=T0,
        updated_at=T0,
    )

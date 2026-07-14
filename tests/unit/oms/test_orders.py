from alphaquant.oms import ExecutionStyle, OrderPlanner, PlanOrderRole
from tests.unit.oms.conftest import T0, make_signal


def test_bracket_signal_creates_order_plan_with_child_orders() -> None:
    planner = OrderPlanner()
    intent = planner.intent_from_signal(make_signal(style="bracket"), now=T0)
    plan = planner.plan(intent, now=T0)

    assert intent.execution_style is ExecutionStyle.BRACKET
    assert len(plan.orders) == 3
    assert plan.orders[0].role is PlanOrderRole.ENTRY
    assert plan.orders[1].submit_immediately is False
    assert plan.orders[2].submit_immediately is False


def test_request_hash_is_stable_for_same_plan_order() -> None:
    planner = OrderPlanner()
    intent = planner.intent_from_signal(make_signal(), now=T0)
    plan = planner.plan(intent, now=T0)

    first = planner.request_hash(plan, plan.orders[0])
    second = planner.request_hash(plan, plan.orders[0])

    assert first == second

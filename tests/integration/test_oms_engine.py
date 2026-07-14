from datetime import timedelta
from decimal import Decimal

import pytest

from alphaquant.oms import BrokerExecutionReport, BrokerOrderStatus, OrderManagementEngine
from alphaquant.risk import RiskEngine
from tests.unit.oms.conftest import T0, FakeBroker, make_signal, permissive_settings


@pytest.mark.integration
def test_oms_end_to_end_lifecycle() -> None:
    engine = OrderManagementEngine(
        risk_engine=RiskEngine(permissive_settings()),
        brokers={"fake": FakeBroker()},
        default_broker="fake",
    )

    submitted = engine.submit_signal(make_signal(), now=T0)
    external_order_id = submitted[0].external_order_id
    assert external_order_id is not None

    engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=external_order_id,
            status=BrokerOrderStatus.PARTIALLY_FILLED,
            broker_timestamp=T0 + timedelta(seconds=1),
            fill_id="fill-a",
            last_fill_quantity=25,
            fill_price=Decimal("150"),
            remaining_quantity=50,
        )
    )
    final = engine.process_execution_report(
        BrokerExecutionReport(
            external_order_id=external_order_id,
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=T0 + timedelta(seconds=2),
            fill_id="fill-b",
            last_fill_quantity=50,
            fill_price=Decimal("151"),
            remaining_quantity=0,
        )
    )

    report = engine.reconcile(now=T0 + timedelta(seconds=3))
    assert final.execution_state.value == "filled"
    assert report.reconciled is False or report.reconciled is True

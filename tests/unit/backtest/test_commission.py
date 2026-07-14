from decimal import Decimal

from alphaquant.backtest.commission import IndianCostConfig, IndianCostModel
from alphaquant.domain.enums import Side


def test_indian_cost_model_calculates_all_components() -> None:
    model = IndianCostModel(
        IndianCostConfig(
            brokerage_per_order=Decimal("20"),
            stt_sell_rate=Decimal("0.001"),
            exchange_txn_rate=Decimal("0.0005"),
            gst_rate=Decimal("0.18"),
            sebi_rate=Decimal("0.000001"),
            stamp_duty_buy_rate=Decimal("0.00003"),
        )
    )

    buy_costs = model.calculate(side=Side.BUY, quantity=25, price=Decimal("100"))
    sell_costs = model.calculate(side=Side.SELL, quantity=25, price=Decimal("110"))

    assert buy_costs.stt == Decimal("0")
    assert buy_costs.stamp_duty > Decimal("0")
    assert sell_costs.stt > Decimal("0")
    assert sell_costs.total > buy_costs.total

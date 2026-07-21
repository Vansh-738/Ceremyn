from decimal import Decimal

import pytest

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import OptionChainEvent
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.config import Settings
from ceremyn.risk import RiskEngine
from tests.unit.backtest.helpers import (
    TestBacktestStrategy,
    make_chain,
    make_strategy_definition,
    make_timestamp_one,
    make_timestamp_two,
)


@pytest.mark.integration
def test_backtest_pipeline_end_to_end() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 10
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    risk_engine = RiskEngine(settings)
    strategy_definition = make_strategy_definition()
    strategy = TestBacktestStrategy(strategy_definition)
    timestamp_one = make_timestamp_one()
    timestamp_two = make_timestamp_two()
    events = (
        OptionChainEvent(
            timestamp=timestamp_one,
            chain=make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101"),
        ),
        OptionChainEvent(
            timestamp=timestamp_two,
            chain=make_chain(timestamp=timestamp_two, last_price="110", bid="109", ask="111"),
        ),
    )
    report = BacktestRunner(
        strategy=strategy,
        definition=strategy_definition,
        risk_engine=risk_engine,
        config=BacktestConfig(),
    ).run(events)

    assert report.performance_report
    assert report.trade_ledger[0].gross_pnl > 0

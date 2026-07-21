from datetime import datetime

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import OptionChainEvent
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.domain import StrategyDefinition
from ceremyn.risk import RiskEngine
from tests.unit.backtest.helpers import TestBacktestStrategy, make_chain


def test_runner_executes_strategy_risk_and_virtual_execution(
    risk_engine: RiskEngine,
    strategy_definition: StrategyDefinition,
    strategy: TestBacktestStrategy,
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
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

    assert len(report.trade_ledger) == 1
    assert report.statistics.total_return > 0
    assert report.final_portfolio.positions == ()
    assert report.strategy_summary["risk_decisions"] == 2

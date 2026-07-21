from datetime import datetime
from decimal import Decimal

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import OptionChainEvent
from ceremyn.backtest.montecarlo import MonteCarloSimulator
from ceremyn.backtest.optimization import GridSearchOptimizer
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.backtest.walkforward import WalkForwardAnalyzer
from ceremyn.domain import StrategyDefinition
from ceremyn.risk import RiskEngine
from ceremyn.strategies import create
from tests.unit.backtest.helpers import make_chain


def test_grid_search_optimizer_runs_all_parameter_combinations(
    risk_engine: RiskEngine,
    strategy_definition: StrategyDefinition,
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
    optimizer = GridSearchOptimizer()
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
    result = optimizer.run(
        definition=strategy_definition,
        parameter_grid={"lots": (1, 2)},
        events=events,
        risk_engine=risk_engine,
        config=BacktestConfig(),
    )

    assert len(result.reports) == 2
    assert result.best_params["lots"] == 2


def test_walkforward_and_montecarlo_produce_outputs(
    risk_engine: RiskEngine,
    strategy_definition: StrategyDefinition,
    timestamp_one: datetime,
    timestamp_two: datetime,
) -> None:
    analyzer = WalkForwardAnalyzer()
    events = (
        OptionChainEvent(
            timestamp=timestamp_one,
            chain=make_chain(timestamp=timestamp_one, last_price="100", bid="99", ask="101"),
        ),
        OptionChainEvent(
            timestamp=timestamp_two,
            chain=make_chain(timestamp=timestamp_two, last_price="110", bid="109", ask="111"),
        ),
        OptionChainEvent(
            timestamp=timestamp_two.replace(hour=11),
            chain=make_chain(
                timestamp=timestamp_two.replace(hour=11),
                last_price="120",
                bid="119",
                ask="121",
            ),
        ),
    )
    windows = analyzer.split(events, train_size=1, validate_size=1, test_size=1)
    result = analyzer.run(
        definition=strategy_definition,
        events=events,
        risk_engine=risk_engine,
        train_size=1,
        validate_size=1,
        test_size=1,
        config=BacktestConfig(),
    )
    report = BacktestRunner(
        strategy=create(strategy_definition),
        definition=strategy_definition,
        risk_engine=risk_engine,
        config=BacktestConfig(),
    ).run(events[:2])
    monte_carlo = MonteCarloSimulator().run(
        equity_curve=report.equity_curve,
        iterations=50,
        ruin_threshold=Decimal("0"),
        seed=3,
    )

    assert len(windows) == 1
    assert len(result.reports) == 1
    assert len(monte_carlo.simulations) == 50
    assert 0.0 <= monte_carlo.probability_of_ruin <= 1.0

from datetime import datetime
from decimal import Decimal

import pytest

from ceremyn.config import Settings
from ceremyn.domain import Side, Signal, SignalAction, SignalLeg, StrategyDefinition
from ceremyn.risk import RiskEngine
from tests.unit.backtest.helpers import (
    TestBacktestStrategy,
    make_contract,
    make_strategy_definition,
    make_timestamp_one,
    make_timestamp_two,
)


@pytest.fixture
def base_settings() -> Settings:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 10
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    return settings


@pytest.fixture
def risk_engine(base_settings: Settings) -> RiskEngine:
    return RiskEngine(base_settings)


@pytest.fixture
def strategy_definition() -> StrategyDefinition:
    return make_strategy_definition()


@pytest.fixture
def strategy(strategy_definition: StrategyDefinition) -> TestBacktestStrategy:
    return TestBacktestStrategy(strategy_definition)


@pytest.fixture
def signal(timestamp_one: datetime) -> Signal:
    contract = make_contract()
    return Signal(
        strategy_id="test_backtest_strategy",
        strategy_version="1",
        created_at=timestamp_one,
        market_timestamp=timestamp_one,
        underlying=contract.underlying,
        expiry=contract.expiry,
        signal_type=SignalAction.ENTER,
        reason="test signal",
        legs=(SignalLeg(contract=contract, side=Side.BUY, lots=1),),
    )


@pytest.fixture
def timestamp_one() -> datetime:
    return make_timestamp_one()


@pytest.fixture
def timestamp_two() -> datetime:
    return make_timestamp_two()

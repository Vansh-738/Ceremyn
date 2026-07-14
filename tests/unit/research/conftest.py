from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from alphaquant.backtest.events import OptionChainEvent
from alphaquant.config import Settings
from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset, dataset_from_events
from alphaquant.research.experiment import Experiment
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.research.experiment_store import InMemoryExperimentStore
from alphaquant.research.statistics import ExperimentMetrics
from alphaquant.risk import RiskEngine
from tests.unit.backtest.helpers import make_chain, make_strategy_definition

START = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)


def make_experiment(
    *,
    experiment_id: str,
    strategy_name: str = "Strategy",
    spec_hash: str | None = None,
    **metric_overrides: float,
) -> Experiment:
    """Build a persisted-style Experiment with explicit metric values (for ranking tests)."""
    return Experiment(
        experiment_id=experiment_id,
        spec_hash=spec_hash or f"hash-{experiment_id}",
        strategy_name=strategy_name,
        market_data_version="mdv-1",
        parameters={"lots": 1},
        metrics=ExperimentMetrics(**metric_overrides),
    )


def price_path_events(
    prices: Sequence[str], *, start: datetime = START
) -> tuple[OptionChainEvent, ...]:
    """Build a stream of single-strike option-chain events following a price path."""
    events = []
    for index, price in enumerate(prices):
        last = Decimal(price)
        timestamp = start + timedelta(hours=index)
        chain = make_chain(
            timestamp=timestamp,
            last_price=str(last),
            bid=str(last - Decimal("0.5")),
            ask=str(last + Decimal("0.5")),
            volume=1000,
        )
        events.append(OptionChainEvent(timestamp=timestamp, chain=chain))
    return tuple(events)


def make_dataset(prices: Sequence[str] | None = None, *, name: str = "test-dataset") -> Dataset:
    path = prices or ["100", "110", "105", "120", "115", "130", "108", "140"]
    return dataset_from_events(name, price_path_events(path))


@pytest.fixture
def dataset() -> Dataset:
    return make_dataset()


@pytest.fixture
def definition() -> StrategyDefinition:
    return make_strategy_definition()


@pytest.fixture
def permissive_settings() -> Settings:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    settings.risk.position.max_lots_per_signal = 100
    settings.risk.margin.max_margin_used = Decimal("100000000")
    settings.risk.margin.max_margin_usage_ratio = 1.0
    return settings


@pytest.fixture
def risk_engine(permissive_settings: Settings) -> RiskEngine:
    return RiskEngine(permissive_settings)


@pytest.fixture
def store() -> InMemoryExperimentStore:
    return InMemoryExperimentStore()


@pytest.fixture
def manager(store: InMemoryExperimentStore) -> ExperimentManager:
    return ExperimentManager(store)

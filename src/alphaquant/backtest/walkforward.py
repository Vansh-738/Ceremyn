"""Walk-forward analysis support."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.engine import BacktestConfig
from alphaquant.backtest.events import BacktestEvent
from alphaquant.backtest.report import BacktestReport
from alphaquant.backtest.runner import BacktestRunner
from alphaquant.domain import StrategyDefinition
from alphaquant.risk import RiskEngine
from alphaquant.strategies import create


class WalkForwardWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    train: tuple[BacktestEvent, ...] = ()
    validation: tuple[BacktestEvent, ...] = ()
    test: tuple[BacktestEvent, ...] = ()


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    windows: tuple[WalkForwardWindow, ...] = ()
    reports: tuple[BacktestReport, ...] = ()


class WalkForwardAnalyzer:
    def split(
        self,
        events: Iterable[BacktestEvent],
        *,
        train_size: int,
        validate_size: int,
        test_size: int,
    ) -> tuple[WalkForwardWindow, ...]:
        event_list = tuple(sorted(events, key=lambda item: item.timestamp))
        windows: list[WalkForwardWindow] = []
        step = test_size
        index = 0
        while index + train_size + validate_size + test_size <= len(event_list):
            windows.append(
                WalkForwardWindow(
                    train=event_list[index : index + train_size],
                    validation=(
                        event_list[index + train_size : index + train_size + validate_size]
                    ),
                    test=event_list[
                        index + train_size + validate_size : index
                        + train_size
                        + validate_size
                        + test_size
                    ],
                )
            )
            index += step
        return tuple(windows)

    def run(
        self,
        *,
        definition: StrategyDefinition,
        events: Iterable[BacktestEvent],
        risk_engine: RiskEngine,
        train_size: int,
        validate_size: int,
        test_size: int,
        config: BacktestConfig | None = None,
    ) -> WalkForwardResult:
        windows = self.split(
            events,
            train_size=train_size,
            validate_size=validate_size,
            test_size=test_size,
        )
        reports = []
        for window in windows:
            combined = window.train + window.validation + window.test
            reports.append(
                BacktestRunner(
                    strategy=create(definition),
                    definition=definition,
                    risk_engine=risk_engine,
                    config=config,
                ).run(combined)
            )
        return WalkForwardResult(windows=windows, reports=tuple(reports))

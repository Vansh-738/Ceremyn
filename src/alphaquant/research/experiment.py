"""Experiment identity, specification, and the persisted experiment record."""

import hashlib
import json
import subprocess
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.backtest.engine import BacktestConfig
from alphaquant.core.timeutils import now_utc
from alphaquant.domain.market_data import _require_aware
from alphaquant.research.statistics import ExperimentMetrics


def git_commit() -> str:
    """Current git commit SHA, or 'unknown' when not in a repo / git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


class ExperimentSpec(BaseModel):
    """The reproducible definition of an experiment.

    Two specs with the same ``spec_hash`` describe the same experiment and are expected
    to produce identical results — this is what lets the manager dedupe reruns.
    """

    model_config = ConfigDict(frozen=True)

    strategy_type: str = Field(min_length=1)
    strategy_name: str = Field(min_length=1)
    strategy_version: str = "1"
    underlyings: tuple[str, ...] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dataset_name: str = Field(min_length=1)
    market_data_version: str = Field(min_length=1)
    feature_version: str = "v1"
    backtest_config: BacktestConfig = Field(default_factory=BacktestConfig)
    notes: str = ""

    @property
    def spec_hash(self) -> str:
        """Deterministic identity over everything that affects the result."""
        payload = _canonical(
            {
                "strategy_type": self.strategy_type,
                "strategy_version": self.strategy_version,
                "underlyings": list(self.underlyings),
                "parameters": self.parameters,
                "market_data_version": self.market_data_version,
                "feature_version": self.feature_version,
                "backtest_config": self.backtest_config.model_dump(mode="json"),
            }
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class Experiment(BaseModel):
    """A completed, persistable experiment record (the M6 experiment model)."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(default_factory=lambda: uuid4().hex)
    spec_hash: str = Field(min_length=1)
    strategy_name: str = Field(min_length=1)
    strategy_version: str = "1"
    git_commit: str = "unknown"
    timestamp: datetime = Field(default_factory=now_utc)
    market_data_version: str = Field(min_length=1)
    feature_version: str = "v1"
    parameters: dict[str, Any] = Field(default_factory=dict)
    metrics: ExperimentMetrics = Field(default_factory=ExperimentMetrics)
    execution_time_seconds: float = Field(default=0.0, ge=0)
    notes: str = ""

    _aware = field_validator("timestamp")(_require_aware)

    @classmethod
    def from_spec(
        cls,
        spec: ExperimentSpec,
        *,
        metrics: ExperimentMetrics,
        execution_time_seconds: float,
        commit: str | None = None,
    ) -> "Experiment":
        return cls(
            spec_hash=spec.spec_hash,
            strategy_name=spec.strategy_name,
            strategy_version=spec.strategy_version,
            git_commit=commit if commit is not None else git_commit(),
            market_data_version=spec.market_data_version,
            feature_version=spec.feature_version,
            parameters=spec.parameters,
            metrics=metrics,
            execution_time_seconds=execution_time_seconds,
            notes=spec.notes,
        )

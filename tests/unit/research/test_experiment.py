from datetime import datetime

import pytest
from pydantic import ValidationError

from alphaquant.research.experiment import Experiment, ExperimentSpec, git_commit
from alphaquant.research.statistics import ExperimentMetrics


def make_spec(**overrides: object) -> ExperimentSpec:
    defaults: dict[str, object] = {
        "strategy_type": "short_strangle",
        "strategy_name": "Short Strangle",
        "underlyings": ("NIFTY",),
        "parameters": {"lots": 1, "target_delta": 0.2},
        "dataset_name": "ds",
        "market_data_version": "mdv-abc",
    }
    defaults.update(overrides)
    return ExperimentSpec.model_validate(defaults)


class TestSpecHash:
    def test_deterministic_and_order_independent(self) -> None:
        a = make_spec(parameters={"lots": 1, "target_delta": 0.2})
        b = make_spec(parameters={"target_delta": 0.2, "lots": 1})
        assert a.spec_hash == b.spec_hash

    def test_changes_with_parameters(self) -> None:
        assert (
            make_spec(parameters={"lots": 1}).spec_hash
            != make_spec(parameters={"lots": 2}).spec_hash
        )

    def test_changes_with_market_data_version(self) -> None:
        assert (
            make_spec(market_data_version="a").spec_hash
            != make_spec(market_data_version="b").spec_hash
        )

    def test_notes_do_not_affect_hash(self) -> None:
        # Notes are metadata, not part of the computation identity.
        assert make_spec(notes="x").spec_hash == make_spec(notes="y").spec_hash


class TestGitCommit:
    def test_returns_a_sha_or_unknown(self) -> None:
        commit = git_commit()
        assert commit == "unknown" or len(commit) == 40

    def test_falls_back_to_unknown_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("git missing")

        monkeypatch.setattr("alphaquant.research.experiment.subprocess.run", boom)
        assert git_commit() == "unknown"

    def test_returns_unknown_on_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def failed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="err")

        monkeypatch.setattr("alphaquant.research.experiment.subprocess.run", failed)
        assert git_commit() == "unknown"


class TestExperiment:
    def test_from_spec_copies_identity_fields(self) -> None:
        spec = make_spec()
        metrics = ExperimentMetrics(sharpe=1.5)
        exp = Experiment.from_spec(
            spec, metrics=metrics, execution_time_seconds=1.25, commit="abc123"
        )
        assert exp.spec_hash == spec.spec_hash
        assert exp.strategy_name == "Short Strangle"
        assert exp.git_commit == "abc123"
        assert exp.market_data_version == "mdv-abc"
        assert exp.parameters == spec.parameters
        assert exp.metrics.sharpe == 1.5
        assert exp.execution_time_seconds == 1.25
        assert exp.experiment_id  # auto-generated

    def test_timestamp_is_timezone_aware(self) -> None:
        exp = Experiment.from_spec(
            make_spec(), metrics=ExperimentMetrics(), execution_time_seconds=0.0, commit="x"
        )
        assert exp.timestamp.tzinfo is not None

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Experiment(
                spec_hash="h",
                strategy_name="s",
                market_data_version="m",
                timestamp=datetime(2026, 7, 1, 10, 0),  # naive
            )

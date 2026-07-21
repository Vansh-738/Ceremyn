from pathlib import Path

from ceremyn.research.experiment import Experiment
from ceremyn.research.experiment_store import (
    ExperimentStore,
    InMemoryExperimentStore,
    JSONExperimentStore,
)
from ceremyn.research.statistics import ExperimentMetrics


def make_experiment(experiment_id: str, spec_hash: str, sharpe: float = 1.0) -> Experiment:
    return Experiment(
        experiment_id=experiment_id,
        spec_hash=spec_hash,
        strategy_name="S",
        market_data_version="mdv",
        metrics=ExperimentMetrics(sharpe=sharpe),
    )


class TestJSONExperimentStore:
    def test_save_and_get_roundtrip(self, tmp_path: Path) -> None:
        store = JSONExperimentStore(tmp_path)
        exp = make_experiment("e1", "h1", sharpe=2.5)
        store.save(exp)
        loaded = store.get("e1")
        assert loaded is not None
        assert loaded.experiment_id == "e1"
        assert loaded.metrics.sharpe == 2.5

    def test_persists_across_store_instances(self, tmp_path: Path) -> None:
        JSONExperimentStore(tmp_path).save(make_experiment("e1", "h1"))
        # A brand-new store over the same root sees the persisted experiment.
        assert JSONExperimentStore(tmp_path).get("e1") is not None

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        assert JSONExperimentStore(tmp_path).get("nope") is None

    def test_list_all_sorted_by_timestamp(self, tmp_path: Path) -> None:
        store = JSONExperimentStore(tmp_path)
        for i in range(3):
            store.save(make_experiment(f"e{i}", f"h{i}"))
        listed = store.list_all()
        assert len(listed) == 3
        assert list(listed) == sorted(listed, key=lambda e: e.timestamp)

    def test_find_by_spec_hash_returns_latest(self, tmp_path: Path) -> None:
        store = JSONExperimentStore(tmp_path)
        store.save(make_experiment("e1", "shared"))
        store.save(make_experiment("e2", "shared"))
        found = store.find_by_spec_hash("shared")
        assert found is not None
        assert found.experiment_id == "e2"  # most recent
        assert store.exists("shared") is True
        assert store.exists("absent") is False

    def test_creates_root_directory(self, tmp_path: Path) -> None:
        root = tmp_path / "nested" / "experiments"
        JSONExperimentStore(root)
        assert root.exists()

    def test_no_leftover_temp_files(self, tmp_path: Path) -> None:
        store = JSONExperimentStore(tmp_path)
        store.save(make_experiment("e1", "h1"))
        assert list(tmp_path.glob("*.tmp")) == []
        assert len(list(tmp_path.glob("*.json"))) == 1

    def test_satisfies_protocol(self, tmp_path: Path) -> None:
        store: ExperimentStore = JSONExperimentStore(tmp_path)
        assert isinstance(store, ExperimentStore)


class TestInMemoryExperimentStore:
    def test_roundtrip_and_queries(self) -> None:
        store = InMemoryExperimentStore()
        store.save(make_experiment("e1", "h1"))
        store.save(make_experiment("e2", "h1"))
        assert store.get("e1") is not None
        assert len(store.list_all()) == 2
        assert store.find_by_spec_hash("h1").experiment_id == "e2"  # type: ignore[union-attr]
        assert store.exists("h1") is True
        assert store.get("missing") is None
        assert store.find_by_spec_hash("missing") is None

    def test_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryExperimentStore(), ExperimentStore)

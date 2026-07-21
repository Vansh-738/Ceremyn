"""Experiment persistence: an append-only store so no experiment is ever lost.

``ExperimentStore`` is the protocol the Research Lab codes against; ``JSONExperimentStore``
is the default implementation (one JSON file per experiment under a root directory). A
Postgres-backed store can be added later against the same protocol without touching Lab logic.
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

from ceremyn.research.experiment import Experiment


@runtime_checkable
class ExperimentStore(Protocol):
    """Append-only experiment persistence."""

    def save(self, experiment: Experiment) -> None: ...

    def get(self, experiment_id: str) -> Experiment | None: ...

    def list_all(self) -> tuple[Experiment, ...]: ...

    def find_by_spec_hash(self, spec_hash: str) -> Experiment | None: ...

    def exists(self, spec_hash: str) -> bool: ...


class JSONExperimentStore:
    """Filesystem store: ``<root>/<experiment_id>.json`` per experiment.

    Writes are atomic (temp file + rename) so a crash never leaves a half-written
    record. Nothing is ever overwritten with a different id, so history is preserved.
    """

    DEFAULT_ROOT = Path("data/research/experiments")

    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, experiment_id: str) -> Path:
        return self.root / f"{experiment_id}.json"

    def save(self, experiment: Experiment) -> None:
        path = self._path(experiment.experiment_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(experiment.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def get(self, experiment_id: str) -> Experiment | None:
        path = self._path(experiment_id)
        if not path.exists():
            return None
        return Experiment.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self) -> tuple[Experiment, ...]:
        experiments = [
            Experiment.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.root.glob("*.json"))
        ]
        experiments.sort(key=lambda item: item.timestamp)
        return tuple(experiments)

    def find_by_spec_hash(self, spec_hash: str) -> Experiment | None:
        """Most recent experiment with this spec hash, or None (for rerun dedup)."""
        matches = [exp for exp in self.list_all() if exp.spec_hash == spec_hash]
        return matches[-1] if matches else None

    def exists(self, spec_hash: str) -> bool:
        return self.find_by_spec_hash(spec_hash) is not None


class InMemoryExperimentStore:
    """Non-persistent store for tests and ephemeral sessions."""

    def __init__(self) -> None:
        self._by_id: dict[str, Experiment] = {}

    def save(self, experiment: Experiment) -> None:
        self._by_id[experiment.experiment_id] = experiment

    def get(self, experiment_id: str) -> Experiment | None:
        return self._by_id.get(experiment_id)

    def list_all(self) -> tuple[Experiment, ...]:
        return tuple(sorted(self._by_id.values(), key=lambda item: item.timestamp))

    def find_by_spec_hash(self, spec_hash: str) -> Experiment | None:
        matches = [exp for exp in self.list_all() if exp.spec_hash == spec_hash]
        return matches[-1] if matches else None

    def exists(self, spec_hash: str) -> bool:
        return self.find_by_spec_hash(spec_hash) is not None

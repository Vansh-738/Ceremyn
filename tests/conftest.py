import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_alphaquant_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip real ALPHAQUANT_* env vars so tests never see developer config."""
    for key in list(os.environ):
        if key.startswith("ALPHAQUANT_"):
            monkeypatch.delenv(key)


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `data/...`-relative default (JSONJournalStore, JSONExperimentStore, ...)
    resolves under a fresh per-test directory, so one test's persisted OMS
    journal/experiment files never leak into another's (each `Container`/store call
    otherwise shares one real, stable, gitignored `data/` path across the whole
    process)."""
    monkeypatch.chdir(tmp_path)

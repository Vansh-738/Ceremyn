import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_alphaquant_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip real ALPHAQUANT_* env vars so tests never see developer config."""
    for key in list(os.environ):
        if key.startswith("ALPHAQUANT_"):
            monkeypatch.delenv(key)

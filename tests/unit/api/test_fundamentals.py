from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ceremyn.api import fundamentals
from ceremyn.config import Settings
from ceremyn.fundamentals.provider import JSONFundamentalsStore
from tests.unit.fundamentals.test_fundamentals import filing


def test_api_is_point_in_time_and_missing_data_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "filings.json"
    JSONFundamentalsStore(path).import_snapshots([filing(2025), filing(2026)])
    settings = Settings(_env_file=None, fundamentals_path=str(path))
    monkeypatch.setattr(fundamentals, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(fundamentals.router)
    client = TestClient(app)
    response = client.get("/equity/TEST", params={"price": 100, "as_of": "2026-07-01T00:00:00Z"})
    assert response.status_code == 200 and response.json()["score"] is not None
    old = client.get("/equity/TEST", params={"price": 100, "as_of": "2026-04-01T00:00:00Z"})
    assert old.json()["score"] is None
    assert client.get("/equity/UNKNOWN", params={"price": 100}).json()["available"] is False
    assert (
        client.get("/equity/TEST", params={"price": 100, "as_of": "2026-01-01"}).status_code == 422
    )

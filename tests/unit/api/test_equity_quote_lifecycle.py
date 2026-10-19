from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ceremyn.api.app import create_app
from ceremyn.config import Settings
from ceremyn.core.container import Container


@pytest.mark.parametrize(
    "enabled,key,token,started",
    [
        (False, "key", "token", False),
        (True, "", "", False),
        (True, "key", "", False),
        (True, "key", "token", True),
    ],
)
def test_quote_job_requires_opt_in_and_credentials_and_stops(
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    key: str,
    token: str,
    started: bool,
) -> None:
    settings = Settings(
        _env_file=None,
        equity_quotes={"enabled": enabled},
        kite={"api_key": key, "access_token": token},
    )
    container = Container(settings)
    app = create_app(settings, container=container)
    for engine in (container.orchestrator,):
        monkeypatch.setattr(engine, "start", AsyncMock())
        monkeypatch.setattr(engine, "stop", AsyncMock())
    container.__dict__["rest_poller"] = AsyncMock()
    job = AsyncMock()
    container.__dict__["equity_quote_job"] = job
    with TestClient(app):
        assert job.start.await_count == int(started)
        job.stop.assert_not_awaited()
    assert job.stop.await_count == int(started)


def test_container_quote_job_shares_cache_and_is_lazy() -> None:
    container = Container(Settings(_env_file=None, kite={"api_key": "test"}))
    assert "equity_quote_job" not in container.__dict__
    assert container.equity_quote_job._cache is container.live_engine.cache
    assert container.equity_quote_job._provider is container.kite_provider
    assert container.equity_quote_job is container.equity_quote_job

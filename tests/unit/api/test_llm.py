"""Full HTTP flow for the LLM assistant router (`api/llm.py`). Built directly via
`build_llm_router` with a fake-backed `Assistant` (no real Anthropic credentials needed),
mirroring `test_execution.py`'s shape for the equally-separate `/execution` router.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from alphaquant.api.llm import _auth_dependency, build_llm_router
from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.permissions import Permission
from alphaquant.llm.assistant import Assistant
from alphaquant.llm.client import ClaudeClient
from alphaquant.llm.conversation import InMemoryConversationStore
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief
from alphaquant.llm.watchlist import InMemoryWatchlistStore
from tests.unit.llm.conftest import FakeAnthropic, FakeContentBlock, FakeMessage, FakeSDKStream

SECRET = "super-secret-viewer-token"


class FakeExperiments:
    def detail(self, experiment_id: str) -> ExperimentDetailBrief | None:
        return None


class FakeRecap:
    def daily(self) -> RecapBrief:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        return RecapBrief(window_label="today", window_start=now, window_end=now)

    def session(self) -> RecapBrief:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        return RecapBrief(window_label="this session", window_start=now, window_end=now)


def text_only(text: str) -> FakeSDKStream:
    return FakeSDKStream([text], FakeMessage(content=[FakeContentBlock(type="text", text=text)]))


def make_app(
    *, turns: list[FakeSDKStream] | None = None, auth_enabled: bool = False
) -> tuple[FastAPI, InMemoryWatchlistStore, FakeAnthropic]:
    fake = FakeAnthropic(turns or [text_only("hello")])
    client = ClaudeClient(fake, model="claude-sonnet-5")
    watchlist = InMemoryWatchlistStore()
    assistant = Assistant(
        client_factory=lambda: client,
        dashboard=DashboardService(DashboardSources()),
        experiments=FakeExperiments(),
        recap=FakeRecap(),
        watchlist=watchlist,
        conversation=InMemoryConversationStore(),
    )
    settings = DashboardSettings(
        auth_enabled=auth_enabled, admin_token="ADMIN", viewer_token=SECRET
    )
    app = FastAPI()
    app.include_router(build_llm_router(assistant, watchlist, settings), prefix="/llm")
    return app, watchlist, fake


def parse_sse(text: str) -> list[dict[str, object]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        if block.startswith("data: "):
            events.append(json.loads(block[len("data: ") :]))
    return events


class TestChat:
    def test_streams_text_and_done(self) -> None:
        app, _, _ = make_app(turns=[text_only("hi there")])
        with TestClient(app) as client:
            response = client.post("/llm/chat", json={"session_id": "s1", "message": "hello"})

        assert response.status_code == 200
        events = parse_sse(response.text)
        assert events[0] == {"type": "text_delta", "text": "hi there"}
        assert events[-1]["type"] == "done"

    def test_empty_message_is_rejected(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.post("/llm/chat", json={"session_id": "s1", "message": ""})
        assert response.status_code == 422

    def test_empty_session_id_is_rejected(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.post("/llm/chat", json={"session_id": "", "message": "hi"})
        assert response.status_code == 422


class TestReports:
    def test_daily_recap_streams(self) -> None:
        app, _, _ = make_app(turns=[text_only("quiet day")])
        with TestClient(app) as client:
            response = client.post("/llm/reports/daily-recap", json={"session_id": "s1"})
        assert response.status_code == 200
        events = parse_sse(response.text)
        assert any(e["type"] == "tool_call" for e in events)
        assert events[-1]["type"] == "done"

    def test_session_recap_streams(self) -> None:
        app, _, _ = make_app(turns=[text_only("quiet session")])
        with TestClient(app) as client:
            response = client.post("/llm/reports/session-recap", json={"session_id": "s1"})
        assert response.status_code == 200
        events = parse_sse(response.text)
        assert events[-1]["type"] == "done"

    def test_generate_report_streams(self) -> None:
        app, _, _ = make_app(turns=[text_only("report text")])
        with TestClient(app) as client:
            response = client.post(
                "/llm/reports/generate", json={"session_id": "s1", "topic": "research summary"}
            )
        assert response.status_code == 200
        events = parse_sse(response.text)
        assert events[0] == {"type": "text_delta", "text": "report text"}

    def test_generate_report_empty_topic_is_rejected(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.post("/llm/reports/generate", json={"session_id": "s1", "topic": ""})
        assert response.status_code == 422


class TestCompareExperiments:
    def test_streams_and_seeds_per_experiment(self) -> None:
        app, _, _ = make_app(turns=[text_only("comparison")])
        with TestClient(app) as client:
            response = client.post(
                "/llm/compare-experiments",
                json={"session_id": "s1", "experiment_ids": ["e1", "e2"]},
            )
        assert response.status_code == 200
        events = parse_sse(response.text)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 2

    def test_empty_experiment_ids_is_rejected(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.post(
                "/llm/compare-experiments", json={"session_id": "s1", "experiment_ids": []}
            )
        assert response.status_code == 422


class TestWatchlist:
    def test_get_empty_watchlist(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.get("/llm/watchlist/s1")
        assert response.status_code == 200
        assert response.json() == {"session_id": "s1", "symbols": []}

    def test_add_and_get(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            add = client.post("/llm/watchlist/s1", json={"action": "add", "symbol": "nifty"})
            assert add.json()["symbols"] == ["NIFTY"]

            got = client.get("/llm/watchlist/s1")
            assert got.json()["symbols"] == ["NIFTY"]

    def test_remove(self) -> None:
        app, watchlist, _ = make_app()
        watchlist.add("s1", "NIFTY")
        with TestClient(app) as client:
            response = client.post(
                "/llm/watchlist/s1", json={"action": "remove", "symbol": "nifty"}
            )
        assert response.json()["symbols"] == []

    def test_invalid_action_is_rejected(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            response = client.post(
                "/llm/watchlist/s1", json={"action": "delete", "symbol": "NIFTY"}
            )
        assert response.status_code == 422

    def test_watchlists_are_isolated_by_session(self) -> None:
        app, _, _ = make_app()
        with TestClient(app) as client:
            client.post("/llm/watchlist/s1", json={"action": "add", "symbol": "NIFTY"})
            other = client.get("/llm/watchlist/s2")
        assert other.json()["symbols"] == []


class TestAuth:
    @pytest.fixture
    def client(self) -> Iterator[TestClient]:
        app, _, _ = make_app(auth_enabled=True)
        with TestClient(app) as test_client:
            yield test_client

    def test_missing_token_is_unauthorized(self, client: TestClient) -> None:
        response = client.get("/llm/watchlist/s1")
        assert response.status_code == 401

    def test_wrong_token_is_unauthorized(self, client: TestClient) -> None:
        # A token that matches neither the admin nor the viewer token can't resolve to a
        # role at all (AuthError, 401) - both roles that DO exist have USE_LLM, so a
        # ForbiddenError (403) can't occur for this permission specifically.
        response = client.get("/llm/watchlist/s1", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401

    def test_correct_token_is_allowed(self, client: TestClient) -> None:
        response = client.get("/llm/watchlist/s1", headers={"Authorization": f"Bearer {SECRET}"})
        assert response.status_code == 200

    def test_chat_also_requires_auth(self, client: TestClient) -> None:
        response = client.post("/llm/chat", json={"session_id": "s1", "message": "hi"})
        assert response.status_code == 401


def test_chat_streams_an_error_frame_on_provider_failure() -> None:
    app, _, fake = make_app()
    fake.messages.fail_next(RuntimeError("provider unavailable"))
    with TestClient(app) as client:
        response = client.post("/llm/chat", json={"session_id": "s1", "message": "hi"})

    assert response.status_code == 200  # streaming already started; error is an SSE frame
    events = parse_sse(response.text)
    assert events[-1]["type"] == "error"
    assert "provider unavailable" in str(events[-1]["message"])


def test_auth_dependency_maps_forbidden_error_to_403() -> None:
    # USE_LLM is granted to every role today, so a real request can never reach this
    # branch; exercise the mapping directly so it's still verified if that ever changes.
    settings = DashboardSettings(auth_enabled=True, admin_token="ADMIN", viewer_token=SECRET)
    dependency = _auth_dependency(Permission.VIEW_LOGS, settings)
    with pytest.raises(HTTPException) as exc_info:
        dependency(f"Bearer {SECRET}")
    assert exc_info.value.status_code == 403


def test_only_get_and_post_are_exposed_under_llm() -> None:
    app, _, _ = make_app()
    methods: set[str] = set()
    for route in app.routes:  # type: ignore[attr-defined]
        methods |= getattr(route, "methods", set()) or set()
    assert methods <= {"GET", "HEAD", "POST"}

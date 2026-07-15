"""The dashboard is mounted into the single production application under /dashboard."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from alphaquant.api.app import create_app
from alphaquant.config import Settings
from alphaquant.core.container import Container
from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.live.events import HeartbeatLost


def make_app() -> object:
    return create_app(Settings(_env_file=None))  # type: ignore[call-arg]


def test_main_entrypoint_builds_the_single_app() -> None:
    from fastapi import FastAPI

    from alphaquant.api.main import app

    assert isinstance(app, FastAPI)


def test_single_app_serves_health_and_dashboard() -> None:
    app = make_app()
    with TestClient(app) as client:  # `with` runs the lifespan (broadcaster start/stop)
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/system/status").status_code == 200


def test_swagger_still_works() -> None:
    with TestClient(make_app()) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


class TestMountedDashboard:
    def test_shell_served_at_dashboard(self) -> None:
        with TestClient(make_app()) as client:
            response = client.get("/dashboard/")
            assert response.status_code == 200
            body = response.text
            # Professional shell markers (not the old minimal demo).
            assert 'data-theme="dark"' in body
            assert 'class="sidebar"' in body
            assert "Live Market" in body
            assert "plotly" in body.lower()

    def test_dashboard_json_endpoints(self) -> None:
        with TestClient(make_app()) as client:
            for path in ("overview", "oms", "metrics", "alerts", "health"):
                assert client.get(f"/dashboard/api/{path}").status_code == 200

    def test_websocket_at_dashboard(self) -> None:
        with (
            TestClient(make_app()) as client,
            client.websocket_connect("/dashboard/ws?channels=overview") as ws,
        ):
            frame = ws.receive_json()
            assert frame["kind"] == "snapshot"
            assert frame["channel"] == "overview"

    def test_no_write_routes_on_whole_app(self) -> None:
        app = make_app()
        methods: set[str] = set()
        for route in app.routes:  # type: ignore[attr-defined]
            methods |= getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD"}


class TestRuntimeWiring:
    """The dashboard reads real runtime state via the composition root, not `None`."""

    def test_default_app_builds_a_container(self) -> None:
        app = make_app()
        assert isinstance(app.state.container, Container)  # type: ignore[attr-defined]

    def test_explicit_dashboard_service_bypasses_the_container(self) -> None:
        app = create_app(
            Settings(_env_file=None),  # type: ignore[call-arg]
            dashboard_service=DashboardService(DashboardSources()),
        )
        assert app.state.container is None  # type: ignore[attr-defined]

    def test_rest_endpoints_reflect_real_engine_state(self) -> None:
        with TestClient(make_app()) as client:
            oms = client.get("/dashboard/api/oms").json()
            assert oms["kill_switch_armed"] is False
            assert oms["reconciled"] is True

            paper = client.get("/dashboard/api/paper").json()
            assert paper["submitted"] == 0

            research = client.get("/dashboard/api/research").json()
            assert research["experiment_count"] == 0

    def test_websocket_receives_live_engine_events_via_event_bridge(self) -> None:
        with (
            TestClient(make_app()) as client,
            client.websocket_connect("/dashboard/ws?channels=health") as ws,
        ):
            ws.receive_json()  # initial snapshot frame

            container = client.app.state.container  # type: ignore[attr-defined]
            event = HeartbeatLost(occurred_at=datetime.now(UTC), last_seen_at=datetime.now(UTC))
            asyncio.run(container.event_bus.publish(event))

            frame = ws.receive_json()
            assert frame["kind"] == "event"
            assert frame["channel"] == "health"
            assert frame["payload"]["event"] == "HeartbeatLost"

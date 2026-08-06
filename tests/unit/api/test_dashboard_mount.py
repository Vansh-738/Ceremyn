"""The dashboard is mounted into the single production application under /dashboard."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from ceremyn.api.app import create_app
from ceremyn.config import Settings
from ceremyn.core.container import Container
from ceremyn.dashboard.backend import DashboardService, DashboardSources
from ceremyn.live.events import HeartbeatLost


def make_app() -> object:
    return create_app(Settings(_env_file=None))  # type: ignore[call-arg]


def test_main_entrypoint_builds_the_single_app() -> None:
    from fastapi import FastAPI

    from ceremyn.api.main import app

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
            assert "Markets" in body
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

    def test_no_write_routes_under_dashboard(self) -> None:
        # Scoped to /dashboard specifically: the dashboard itself must stay read-only.
        # /execution/* is a deliberately separate, gated admin surface (see
        # TestRuntimeWiring below) and is expected to carry POST routes.
        app = make_app()
        methods: set[str] = set()
        for route in app.routes:  # type: ignore[attr-defined]
            path = getattr(route, "path", "")
            if path.startswith("/dashboard"):
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


class TestExecutionRouterSeparation:
    """`/execution` (arm/disarm — state-mutating) is a deliberately separate, gated admin
    surface. The dashboard only ever gets a read-only GET view of the same gate state
    (`/dashboard/api/execution`) via the normal read-port pattern — never the arm/disarm
    actions themselves."""

    def test_arm_and_disarm_are_not_reachable_under_dashboard(self) -> None:
        app = make_app()
        paths = {getattr(route, "path", "") for route in app.routes}  # type: ignore[attr-defined]
        assert "/execution/status" in paths
        assert "/execution/arm" in paths
        assert "/execution/disarm" in paths
        assert "/dashboard/api/execution/arm" not in paths
        assert "/dashboard/api/execution/disarm" not in paths

    def test_dashboard_execution_channel_is_read_only(self) -> None:
        app = make_app()
        for route in app.routes:  # type: ignore[attr-defined]
            if getattr(route, "path", "") == "/dashboard/api/execution":
                assert getattr(route, "methods", set()) <= {"GET", "HEAD"}
                return
        raise AssertionError("expected /dashboard/api/execution to be mounted")

    def test_execution_router_absent_when_dashboard_service_is_explicit(self) -> None:
        # No container -> no live_trading_gate to wire -> no /execution routes at all.
        app = create_app(
            Settings(_env_file=None),  # type: ignore[call-arg]
            dashboard_service=DashboardService(DashboardSources()),
        )
        paths = {getattr(route, "path", "") for route in app.routes}  # type: ignore[attr-defined]
        assert not any(path.startswith("/execution") for path in paths)


class TestLLMRouterSeparation:
    """`/llm` (the analysis-only assistant, M12) is a deliberately separate router. It reads
    through the same `DashboardService` the dashboard renders from, but is never reachable
    under `/dashboard`, and mounting it never pulls execution/OMS write surfaces along with it."""

    def test_llm_routes_are_not_reachable_under_dashboard(self) -> None:
        app = make_app()
        paths = {getattr(route, "path", "") for route in app.routes}  # type: ignore[attr-defined]
        assert "/llm/chat" in paths
        assert "/llm/watchlist/{session_id}" in paths
        assert not any(path.startswith("/dashboard/llm") for path in paths)
        assert not any(path.startswith("/dashboard") and "/llm" in path for path in paths)

    def test_llm_router_absent_when_dashboard_service_is_explicit(self) -> None:
        # No container -> no Assistant to build (needs Container's engines/stores) -> no
        # /llm routes at all, same as /execution.
        app = create_app(
            Settings(_env_file=None),  # type: ignore[call-arg]
            dashboard_service=DashboardService(DashboardSources()),
        )
        paths = {getattr(route, "path", "") for route in app.routes}  # type: ignore[attr-defined]
        assert not any(path.startswith("/llm") for path in paths)

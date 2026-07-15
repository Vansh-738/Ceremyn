import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from alphaquant.dashboard.api import create_dashboard_app
from alphaquant.dashboard.backend import DashboardService
from alphaquant.dashboard.config import DashboardSettings

VIEW_PATHS = [
    "/api/overview",
    "/api/portfolio",
    "/api/orders",
    "/api/positions",
    "/api/live",
    "/api/features",
    "/api/risk",
    "/api/oms",
    "/api/research",
    "/api/paper",
    "/api/health",
    "/api/metrics",
    "/api/alerts",
]


@pytest.fixture
def client(service: DashboardService) -> TestClient:
    return TestClient(create_dashboard_app(service))


class TestReadEndpoints:
    @pytest.mark.parametrize("path", VIEW_PATHS)
    def test_view_returns_200(self, client: TestClient, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 200
        assert isinstance(response.json(), dict)

    def test_orders_pagination_param(self, client: TestClient) -> None:
        assert client.get("/api/orders?page=2").status_code == 200

    def test_shell_served(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "plotly" in response.text.lower()
        assert "AlphaQuant" in response.text


class TestReadOnlySurface:
    def test_only_get_and_head_methods(self, service: DashboardService) -> None:
        app = create_dashboard_app(service)
        methods: set[str] = set()
        for route in app.routes:
            methods |= getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD"}


class TestAuth:
    def _client(self, service: DashboardService) -> TestClient:
        settings = DashboardSettings(auth_enabled=True, admin_token="ADMIN", viewer_token="VIEW")
        return TestClient(create_dashboard_app(service, settings=settings))

    def test_missing_token_is_401(self, service: DashboardService) -> None:
        assert self._client(service).get("/api/overview").status_code == 401

    def test_viewer_token_allows_dashboard(self, service: DashboardService) -> None:
        response = self._client(service).get(
            "/api/overview", headers={"Authorization": "Bearer VIEW"}
        )
        assert response.status_code == 200

    def test_viewer_forbidden_from_logs(self, service: DashboardService) -> None:
        response = self._client(service).get("/api/logs", headers={"Authorization": "Bearer VIEW"})
        assert response.status_code == 403

    def test_admin_can_read_logs(self, service: DashboardService) -> None:
        response = self._client(service).get("/api/logs", headers={"Authorization": "Bearer ADMIN"})
        assert response.status_code == 200

    def test_invalid_token_is_401(self, service: DashboardService) -> None:
        response = self._client(service).get(
            "/api/overview", headers={"Authorization": "Bearer WRONG"}
        )
        assert response.status_code == 401


class TestWebSocket:
    def test_initial_snapshot_and_control(self, client: TestClient) -> None:
        with client.websocket_connect("/ws?channels=overview") as ws:
            frame = ws.receive_json()
            assert frame["kind"] == "snapshot"
            assert frame["channel"] == "overview"
            ws.send_json({"action": "subscribe", "channels": ["oms"]})
            assert ws.receive_json()["kind"] == "ack"
            ws.send_json({"action": "unsubscribe", "channels": ["overview"]})
            assert ws.receive_json()["kind"] == "ack"

    def test_invalid_channel_is_ignored(self, client: TestClient) -> None:
        with client.websocket_connect("/ws?channels=bogus&channels=overview") as ws:
            frame = ws.receive_json()
            assert frame["channel"] == "overview"

    def test_default_channels_when_unspecified(self, client: TestClient) -> None:
        with client.websocket_connect("/ws") as ws:
            frame = ws.receive_json()
            assert frame["kind"] == "snapshot"

    def test_auth_rejects_without_token(self, service: DashboardService) -> None:
        settings = DashboardSettings(auth_enabled=True, admin_token="ADMIN", viewer_token="VIEW")
        secured = TestClient(create_dashboard_app(service, settings=settings))
        with pytest.raises(WebSocketDisconnect), secured.websocket_connect("/ws") as ws:
            ws.receive_json()

    def test_auth_accepts_with_token(self, service: DashboardService) -> None:
        settings = DashboardSettings(auth_enabled=True, viewer_token="VIEW")
        secured = TestClient(create_dashboard_app(service, settings=settings))
        with secured.websocket_connect("/ws?token=VIEW&channels=overview") as ws:
            assert ws.receive_json()["kind"] == "snapshot"

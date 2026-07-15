"""Read-only dashboard API: GET endpoints, the WebSocket route, and the HTML shell.

Every route is read-only. There is no POST/PUT/DELETE and no order/broker endpoint —
the dashboard can only observe. `build_dashboard_router` returns a router that the main
app can mount with one `include_router`; `create_dashboard_app` builds a standalone app.
"""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse

from alphaquant.dashboard.backend import DashboardService
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.events import SnapshotDiffer
from alphaquant.dashboard.models import Channel
from alphaquant.dashboard.permissions import (
    AuthError,
    ForbiddenError,
    Permission,
    Role,
    authorize,
    bearer_token,
)
from alphaquant.dashboard.websocket import ConnectionManager, broadcast_changes

# Minimal single-page shell: opens the WebSocket, subscribes to the active view's channel,
# and renders pushed frames (tables + Plotly charts from the CDN). API-first — any richer
# SPA can consume the same JSON/WS.
SHELL_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>AlphaQuant Observability</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{font-family:system-ui,sans-serif;margin:0;display:flex}
nav{background:#1a202c;color:#fff;width:180px;min-height:100vh;padding:1rem}
nav a{display:block;color:#cbd5e0;text-decoration:none;padding:6px 4px;cursor:pointer}
nav a:hover{color:#fff}main{flex:1;padding:1.5rem}pre{background:#f7fafc;padding:1rem;overflow:auto}
</style></head><body>
<nav id="nav"></nav>
<main><h2 id="title">Overview</h2><div id="chart"></div><pre id="content">connecting...</pre></main>
<script>
const CHANNELS=["overview","portfolio","orders","positions","live","features","risk",
"oms","research","paper","health","logs","metrics","alerts"];
let active="overview";
const nav=document.getElementById("nav");
CHANNELS.forEach(c=>{const a=document.createElement("a");a.textContent=c;
a.onclick=()=>{active=c;document.getElementById("title").textContent=c};nav.appendChild(a)});
const proto=location.protocol==="https:"?"wss":"ws";
const ws=new WebSocket(`${proto}://${location.host}/ws`);
ws.onmessage=(e)=>{const f=JSON.parse(e.data);
 if(f.channel===active){document.getElementById("content").textContent=JSON.stringify(f.payload,null,2);}};
</script></body></html>
"""


def _auth_dependency(
    permission: Permission, settings: DashboardSettings
) -> Callable[[str | None], Role]:
    def dependency(authorization: str | None = Header(default=None)) -> Role:
        token = bearer_token(authorization)
        try:
            return authorize(token, permission, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return dependency


def build_dashboard_router(
    service: DashboardService,
    *,
    settings: DashboardSettings | None = None,
    manager: ConnectionManager | None = None,
    differ: SnapshotDiffer | None = None,
) -> APIRouter:
    settings = settings or service.settings
    manager = manager or ConnectionManager()
    differ = differ or SnapshotDiffer()
    router = APIRouter()

    view_dashboard = Depends(_auth_dependency(Permission.VIEW_DASHBOARD, settings))
    view_logs = Depends(_auth_dependency(Permission.VIEW_LOGS, settings))

    @router.get("/", response_class=HTMLResponse)
    def shell() -> str:
        return SHELL_HTML

    @router.get("/api/overview", dependencies=[view_dashboard])
    def overview() -> dict[str, Any]:
        return service.overview().model_dump(mode="json")

    @router.get("/api/portfolio", dependencies=[view_dashboard])
    def portfolio() -> dict[str, Any]:
        return service.portfolio().model_dump(mode="json")

    @router.get("/api/orders", dependencies=[view_dashboard])
    def orders(page: int = Query(default=1, ge=1)) -> dict[str, Any]:
        return service.orders(page=page).model_dump(mode="json")

    @router.get("/api/positions", dependencies=[view_dashboard])
    def positions() -> dict[str, Any]:
        return service.positions().model_dump(mode="json")

    @router.get("/api/live", dependencies=[view_dashboard])
    def live() -> dict[str, Any]:
        return service.live().model_dump(mode="json")

    @router.get("/api/features", dependencies=[view_dashboard])
    def features() -> dict[str, Any]:
        return service.features().model_dump(mode="json")

    @router.get("/api/risk", dependencies=[view_dashboard])
    def risk() -> dict[str, Any]:
        return service.risk().model_dump(mode="json")

    @router.get("/api/oms", dependencies=[view_dashboard])
    def oms() -> dict[str, Any]:
        return service.oms().model_dump(mode="json")

    @router.get("/api/research", dependencies=[view_dashboard])
    def research() -> dict[str, Any]:
        return service.research().model_dump(mode="json")

    @router.get("/api/paper", dependencies=[view_dashboard])
    def paper() -> dict[str, Any]:
        return service.paper().model_dump(mode="json")

    @router.get("/api/health", dependencies=[view_dashboard])
    def health() -> dict[str, Any]:
        return service.health().model_dump(mode="json")

    @router.get("/api/metrics", dependencies=[view_dashboard])
    def metrics() -> dict[str, Any]:
        return service.metrics().model_dump(mode="json")

    @router.get("/api/alerts", dependencies=[view_dashboard])
    def alerts() -> dict[str, Any]:
        return service.alerts().model_dump(mode="json")

    @router.get("/api/logs", dependencies=[view_logs])
    def logs() -> dict[str, Any]:
        return service.logs().model_dump(mode="json")

    @router.websocket("/ws")
    async def ws(
        websocket: WebSocket,
        token: str | None = Query(default=None),
        channels: list[str] | None = Query(default=None),
    ) -> None:
        try:
            authorize(token, Permission.VIEW_DASHBOARD, settings)
        except (AuthError, ForbiddenError):
            await websocket.close(code=4401)
            return
        selected = _parse_channels(channels)
        await websocket.accept()
        connection = manager.add(websocket, selected)
        for frame in differ.snapshot_all(service, selected):
            await websocket.send_json(frame.model_dump(mode="json"))
        try:
            while True:
                message = await websocket.receive_json()
                _handle_control(manager, connection, message)
                await websocket.send_json({"kind": "ack", "channel": "", "payload": message})
        except WebSocketDisconnect:
            manager.remove(connection)

    return router


def _parse_channels(channels: list[str] | None) -> tuple[Channel, ...]:
    if not channels:
        return tuple(Channel)
    result: list[Channel] = []
    for name in channels:
        try:
            result.append(Channel(name))
        except ValueError:
            continue
    return tuple(result) or tuple(Channel)


def _handle_control(
    manager: ConnectionManager, connection: object, message: dict[str, Any]
) -> None:
    from alphaquant.dashboard.websocket import Connection

    assert isinstance(connection, Connection)
    action = message.get("action")
    channels = _parse_channels(message.get("channels"))
    if action == "subscribe":
        manager.subscribe(connection, channels)
    elif action == "unsubscribe":
        manager.unsubscribe(connection, channels)


def create_dashboard_app(
    service: DashboardService,
    *,
    settings: DashboardSettings | None = None,
    enable_broadcaster: bool = False,
) -> FastAPI:
    settings = settings or service.settings
    manager = ConnectionManager()
    differ = SnapshotDiffer()
    app = FastAPI(title=settings.title)
    app.include_router(
        build_dashboard_router(service, settings=settings, manager=manager, differ=differ)
    )
    app.state.dashboard_manager = manager
    app.state.dashboard_differ = differ

    if enable_broadcaster:  # pragma: no cover - exercised via run_broadcaster unit

        @app.on_event("startup")
        async def _start() -> None:
            app.state.broadcaster = asyncio.create_task(
                run_broadcaster(service, differ, manager, settings)
            )

        @app.on_event("shutdown")
        async def _stop() -> None:
            task = getattr(app.state, "broadcaster", None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return app


async def run_broadcaster(
    service: DashboardService,
    differ: SnapshotDiffer,
    manager: ConnectionManager,
    settings: DashboardSettings,
) -> None:  # pragma: no cover - infinite loop; one iteration tested via broadcast_changes
    while True:
        await asyncio.sleep(settings.push_interval_seconds)
        await broadcast_changes(service, differ, manager)

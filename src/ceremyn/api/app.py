"""FastAPI application factory — the single production application.

This is the only production entry point (`uvicorn ceremyn.api.main:app`). It serves the
health/system endpoints, the Swagger docs (`/docs`), and mounts three independent routers:
the read-only observability dashboard (`/dashboard`), the triple-gated live-trading admin
surface (`/execution`, M13), and the read-only LLM assistant (`/llm`, M12). There is no
second FastAPI application, and each router is structurally separate from the others.

The dashboard is presentation only: it is wired with read-only sources and can never place an
order. By default everything reads from a `Container` (the composition root,
`core/container.py`) built from `settings` — the live/OMS/paper/risk/feature/research engines
are real, singleton instances; they render honest zero-state until something actually happens
(no fabricated data). Passing an explicit `dashboard_service` (tests only) bypasses the
container entirely — and with it, `/execution` and `/llm`, which both need a real container.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

import ceremyn
from ceremyn.api.execution import build_execution_router
from ceremyn.api.llm import build_llm_router
from ceremyn.api.llm_runtime import build_assistant
from ceremyn.api.runtime import build_dashboard_sources
from ceremyn.config import Settings, get_settings
from ceremyn.core.container import Container
from ceremyn.core.logging import configure_logging
from ceremyn.dashboard.api import build_dashboard_router, run_broadcaster
from ceremyn.dashboard.backend import DashboardService
from ceremyn.dashboard.config import DashboardSettings
from ceremyn.dashboard.events import EventBridge, SnapshotDiffer
from ceremyn.dashboard.models import WSFrame
from ceremyn.dashboard.websocket import ConnectionManager

DASHBOARD_PREFIX = "/dashboard"
EXECUTION_PREFIX = "/execution"
LLM_PREFIX = "/llm"


class _FrameSink:
    """Adapts `ConnectionManager` to `EventBridge`'s `FrameSink` protocol.

    `ConnectionManager.broadcast` returns the number of clients it reached (used by the
    snapshot broadcaster to count sends); `FrameSink.broadcast` returns `None`. This just
    discards that count for the event-bridge path, without changing `ConnectionManager`.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def broadcast(self, frame: WSFrame) -> None:
        await self._manager.broadcast(frame)


class SystemStatus(BaseModel):
    version: str
    environment: str
    configured_mode: str
    effective_mode: str
    live_trading_enabled: bool
    kite_api_configured: bool
    kite_access_token_configured: bool
    active_strategy_ids: tuple[str, ...]
    runtime_ready: bool


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
    dashboard_service: DashboardService | None = None,
    dashboard_settings: DashboardSettings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    dashboard_settings = dashboard_settings or DashboardSettings()
    # An explicit `dashboard_service` (tests only) bypasses the composition root
    # entirely — no container is built, so nothing here touches an engine.
    if dashboard_service is not None:
        service = dashboard_service
        container = None
    else:
        container = container or Container(settings)
        service = DashboardService(build_dashboard_sources(container), dashboard_settings)
    manager = ConnectionManager()
    differ = SnapshotDiffer()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The snapshot broadcaster pushes changed channels to connected dashboard clients
        # on a fixed poll; the event bridge (when a container is wired) pushes live engine
        # events (heartbeat/reconnect/market open-close) the instant they're published.
        # The orchestrator (also only when a real container exists — the dashboard-service
        # test bypass never touches an engine) owns the actual trading lifecycle: starting
        # the live feed, driving strategies through risk/OMS, and graceful shutdown.
        # The REST poller (a simpler alternative to the WebSocket orchestrator, needing
        # no database) only starts when a Kite API key is actually configured — same
        # lazy-credential discipline as every other Kite-touching engine here.
        poller_started = container is not None and bool(container.settings.kite.api_key)
        if container is not None:
            EventBridge().register(container.event_bus, _FrameSink(manager))
            await container.orchestrator.start()
            if poller_started:
                await container.rest_poller.start()
        task = asyncio.create_task(run_broadcaster(service, differ, manager, dashboard_settings))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            if container is not None:
                await container.orchestrator.stop()
                if poller_started:
                    await container.rest_poller.stop()

    app = FastAPI(title="Ceremyn", version=ceremyn.__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        active_strategy_ids: tuple[str, ...] = ()
        if container is not None:
            active_strategy_ids = tuple(
                strategy.definition.id for strategy in container.active_runtime_strategies
            )
        kite_api_configured = bool(settings.kite.api_key)
        kite_access_token_configured = bool(settings.kite.access_token.get_secret_value())
        runtime_ready = bool(active_strategy_ids) and kite_api_configured
        return SystemStatus(
            version=ceremyn.__version__,
            environment=settings.environment,
            configured_mode=settings.trading_mode.value,
            effective_mode=settings.effective_mode.value,
            live_trading_enabled=settings.live_trading_enabled,
            kite_api_configured=kite_api_configured,
            kite_access_token_configured=kite_access_token_configured,
            active_strategy_ids=active_strategy_ids,
            runtime_ready=runtime_ready,
        )

    app.include_router(
        build_dashboard_router(service, settings=dashboard_settings, manager=manager),
        prefix=DASHBOARD_PREFIX,
    )
    if container is not None:
        # Separate from /dashboard by construction: the dashboard router is built above
        # from read-only sources alone and never sees the gate or a broker.
        app.include_router(
            build_execution_router(container.live_trading_gate, settings),
            prefix=EXECUTION_PREFIX,
        )
        # Also separate from /dashboard and /execution: the assistant is read-only and
        # incapable of ordering by construction (see ceremyn.llm's own docstring), but
        # it's still its own router so a future change to one surface can't leak into another.
        app.include_router(
            build_llm_router(
                build_assistant(container, service), container.watchlist_store, dashboard_settings
            ),
            prefix=LLM_PREFIX,
        )
    app.state.dashboard_manager = manager
    app.state.dashboard_differ = differ
    app.state.dashboard_service = service
    app.state.container = container
    return app

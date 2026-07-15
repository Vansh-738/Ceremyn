"""FastAPI application factory — the single production application.

This is the only production entry point (`uvicorn alphaquant.api.main:app`). It serves the
health/system endpoints, the Swagger docs (`/docs`), and mounts the read-only observability
dashboard under `/dashboard` (UI at `/dashboard/`, JSON at `/dashboard/api/*`, live updates
at `/dashboard/ws`). There is no second FastAPI application.

The dashboard is presentation only: it is wired with read-only sources and can never place an
order. Until the live/OMS/paper engines are wired into the composition root, the dashboard
renders with empty sources (structure with no data) and populates as those sources connect.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

import alphaquant
from alphaquant.config import Settings, get_settings
from alphaquant.core.logging import configure_logging
from alphaquant.dashboard.api import build_dashboard_router, run_broadcaster
from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.dashboard.config import DashboardSettings
from alphaquant.dashboard.events import SnapshotDiffer
from alphaquant.dashboard.websocket import ConnectionManager

DASHBOARD_PREFIX = "/dashboard"


class SystemStatus(BaseModel):
    version: str
    environment: str
    configured_mode: str
    effective_mode: str
    live_trading_enabled: bool


def create_app(
    settings: Settings | None = None,
    *,
    dashboard_service: DashboardService | None = None,
    dashboard_settings: DashboardSettings | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    dashboard_settings = dashboard_settings or DashboardSettings()
    service = dashboard_service or DashboardService(DashboardSources(), dashboard_settings)
    manager = ConnectionManager()
    differ = SnapshotDiffer()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # The snapshot broadcaster pushes changed channels to connected dashboard clients.
        task = asyncio.create_task(run_broadcaster(service, differ, manager, dashboard_settings))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="AlphaQuant", version=alphaquant.__version__, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        return SystemStatus(
            version=alphaquant.__version__,
            environment=settings.environment,
            configured_mode=settings.trading_mode.value,
            effective_mode=settings.effective_mode.value,
            live_trading_enabled=settings.live_trading_enabled,
        )

    app.include_router(
        build_dashboard_router(service, settings=dashboard_settings, manager=manager),
        prefix=DASHBOARD_PREFIX,
    )
    app.state.dashboard_manager = manager
    app.state.dashboard_differ = differ
    app.state.dashboard_service = service
    return app

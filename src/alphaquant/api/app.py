"""FastAPI application factory.

M0 scaffold: health and system-status endpoints only, so the Docker image has a
runnable entrypoint from day one. Feature routers are added in M7.
"""

from fastapi import FastAPI
from pydantic import BaseModel

import alphaquant
from alphaquant.config import Settings, get_settings
from alphaquant.core.logging import configure_logging


class SystemStatus(BaseModel):
    version: str
    environment: str
    configured_mode: str
    effective_mode: str
    live_trading_enabled: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="AlphaQuant", version=alphaquant.__version__)

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

    return app

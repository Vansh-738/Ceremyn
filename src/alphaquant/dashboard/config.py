"""Dashboard configuration.

Standalone settings (own ``ALPHAQUANT_DASHBOARD__`` env prefix) so the dashboard does
not modify the completed application ``Settings``. Tokens are provisioned out-of-band by
the operator; the dashboard never collects credentials.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALPHAQUANT_DASHBOARD__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    title: str = "AlphaQuant Observability"
    # When False (dev), every request is granted the VIEWER role. When True (prod),
    # a valid bearer token is required.
    auth_enabled: bool = False
    admin_token: str = ""
    viewer_token: str = ""
    # WebSocket snapshot broadcaster cadence and client liveness ping.
    push_interval_seconds: float = 1.0
    heartbeat_interval_seconds: float = 15.0
    # Pagination default for orders / logs.
    page_size: int = 50

"""Application settings, loaded from environment variables / .env.

All variables use the ``ALPHAQUANT_`` prefix; nested groups use ``__`` as the
delimiter (e.g. ``ALPHAQUANT_DB__HOST``). See .env.example for the full list.
"""

from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from alphaquant.config.modes import TradingMode


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "alphaquant"
    password: SecretStr = SecretStr("change-me")
    name: str = "alphaquant"

    @property
    def url(self) -> str:
        """SQLAlchemy async URL (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


class KiteSettings(BaseModel):
    api_key: str = ""
    api_secret: SecretStr = SecretStr("")


class AnthropicSettings(BaseModel):
    api_key: SecretStr = SecretStr("")
    model: str = "claude-sonnet-5"


class DataSettings(BaseModel):
    underlyings: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
    # Annualized risk-free rate used for greeks/IV (proxy: 91-day T-bill yield).
    risk_free_rate: float = 0.065
    # Cadence of intraday option-chain snapshots during market hours.
    snapshot_interval_minutes: int = 5


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALPHAQUANT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    trading_mode: TradingMode = TradingMode.RESEARCH
    environment: str = "dev"
    log_level: str = "INFO"

    # Live-trading gate #2. Gate #1 is trading_mode == LIVE; gate #3 is the
    # runtime arming token, which never lives in configuration.
    live_trading_enabled: bool = False

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kite: KiteSettings = Field(default_factory=KiteSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    data: DataSettings = Field(default_factory=DataSettings)

    @property
    def effective_mode(self) -> TradingMode:
        """The mode the platform actually runs in.

        LIVE degrades to PAPER unless the config gate is also open. The third
        gate (runtime arming) is enforced by the execution layer on top of
        this; settings alone can never authorize a live order.
        """
        if self.trading_mode is TradingMode.LIVE and not self.live_trading_enabled:
            return TradingMode.PAPER
        return self.trading_mode


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings instance (cached; cleared in tests)."""
    return Settings()

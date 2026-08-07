"""Application settings, loaded from environment variables / .env.

All variables use the ``CEREMYN_`` prefix; nested groups use ``__`` as the
delimiter (e.g. ``CEREMYN_DB__HOST``). See .env.example for the full list.
"""

from datetime import time
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ceremyn.config.modes import TradingMode


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "ceremyn"
    password: SecretStr = SecretStr("change-me")
    name: str = "ceremyn"

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
    # Kite's daily-expiring session token (obtained via scripts/kite_login.py).
    # Never lives longer than one trading day — refresh it each morning.
    access_token: SecretStr = SecretStr("")


class AnthropicSettings(BaseModel):
    api_key: SecretStr = SecretStr("")
    model: str = "claude-sonnet-5"


class ExecutionSettings(BaseModel):
    # Validates gate #3 (runtime arming). The armed state itself never lives here —
    # only the shared secret required to set it. Empty by default: arming is refused
    # (no secret can match) until this is explicitly configured.
    arming_secret: SecretStr = SecretStr("")


class RuntimeSettings(BaseModel):
    # Cadence of the orchestrator's maintenance loop: fill polling, heartbeat
    # staleness checks, and reconciliation.
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    # Strategies intentionally active in the day-to-day runtime. Kept explicit here
    # so the platform does something useful by default, but only with a small,
    # operator-auditable roster.
    active_strategy_types: tuple[str, ...] = ("long_contrarian",)

    @field_validator("active_strategy_types", mode="before")
    @classmethod
    def _parse_strategy_types(cls, value: object) -> object:
        if isinstance(value, str):
            items = tuple(part.strip() for part in value.split(",") if part.strip())
            return items or ("long_contrarian",)
        return value


class PortfolioSettings(BaseModel):
    # Starting cash for the paper/simulated portfolio. Set this to your real
    # capital so position sizing and P&L are meaningful, not a placeholder.
    initial_cash: Decimal = Field(default=Decimal("1000000"), gt=0)


class DataSettings(BaseModel):
    underlyings: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
    # Annualized risk-free rate used for greeks/IV (proxy: 91-day T-bill yield).
    risk_free_rate: float = 0.065
    # Cadence of intraday option-chain snapshots during market hours.
    snapshot_interval_minutes: int = 5


class OpportunitiesSettings(BaseModel):
    """Background pattern-opportunity scan (dashboard Markets page). Off by
    default -- a real scan is a real, repeated NSE bhavcopy fetch across
    hundreds of trading days, not something to run implicitly (e.g. every time
    a test spins up an app). Enable explicitly once you actually want it."""

    scan_enabled: bool = False
    # "watchlist" = the small built-in liquid names; "nifty500" = NSE's own
    # published NIFTY 500 constituent list (index-vetted, but market-cap-tiered
    # by construction); "all_equities" (default) = every listed symbol --
    # deliberately not narrowed by market cap. The one thing this scan commits
    # to as a quality bar is liquidity (min_avg_daily_turnover below), not cap.
    universe: Literal["watchlist", "nifty500", "all_equities"] = "all_equities"
    # The real, load-bearing quality bar: average daily traded value (close price
    # x volume) over the lookback window. Thin daily turnover, not nominal market
    # cap, is what makes a stock cheap to move with a small amount of money.
    min_avg_daily_turnover: Decimal = Field(default=Decimal("10000000"), ge=0)  # ~1 crore/day
    # How far forward (in trading days) each pattern's historical hit-rate/return
    # is measured -- a month-plus horizon, not a quick 5-day flip.
    forward_days: int = Field(default=30, gt=0)
    # A pattern with real, if modest, evidence for its own direction is still
    # not worth acting on if the typical move is tiny. Compared against the
    # *magnitude* of the average move, not its sign (see find_opportunities).
    min_avg_forward_return_pct: float = Field(default=15.0, ge=0)
    scan_interval_hours: float = Field(default=6.0, gt=0)
    lookback_days: int = Field(default=400, gt=0)


class RiskPositionSettings(BaseModel):
    max_open_positions: int = Field(default=20, gt=0)
    max_positions_per_underlying: int = Field(default=10, gt=0)
    max_lots_per_signal: int = Field(default=10, gt=0)


class RiskMarginSettings(BaseModel):
    max_margin_used: Decimal = Field(default=Decimal("1000000"), ge=0)
    max_margin_usage_ratio: float = Field(default=0.8, gt=0, le=1)
    # Same ratios `backtest.portfolio.PortfolioConfig` uses to compute *actual* margin
    # from filled positions — kept here too so `RiskContext.projected_margin_used` can
    # estimate a signal's own margin need with the same model before it's ever
    # submitted, instead of only checking margin already used by prior fills.
    short_option_margin_ratio: Decimal = Field(default=Decimal("0.15"), ge=0)
    long_option_margin_ratio: Decimal = Field(default=Decimal("0.0"), ge=0)


class RiskDrawdownSettings(BaseModel):
    max_daily_loss: Decimal = Field(default=Decimal("50000"), ge=0)
    max_drawdown: Decimal = Field(default=Decimal("200000"), ge=0)


class RiskGreeksSettings(BaseModel):
    max_abs_delta: float = Field(default=5000.0, ge=0)
    max_abs_gamma: float = Field(default=200.0, ge=0)
    max_abs_vega: float = Field(default=5000.0, ge=0)
    max_abs_theta: float = Field(default=5000.0, ge=0)


class RiskLiquiditySettings(BaseModel):
    min_liquidity_score: float = Field(default=0.25, ge=0, le=1)
    max_bid_ask_spread_ratio: float = Field(default=0.02, ge=0)


class RiskTimeSettings(BaseModel):
    trading_start: time = time(hour=9, minute=15)
    trading_end: time = time(hour=15, minute=30)
    allow_expiry_day: bool = False
    min_days_to_expiry: int = Field(default=1, ge=0)


class RiskVolatilitySettings(BaseModel):
    max_implied_volatility: float = Field(default=0.35, ge=0)
    max_volatility_percentile: float = Field(default=0.9, ge=0, le=1)


class RiskEventSettings(BaseModel):
    block_on_high_impact: bool = True
    blocked_event_types: tuple[str, ...] = ("RBI_POLICY", "CPI", "FED", "BUDGET")


class RiskExposureSettings(BaseModel):
    max_gross_notional: Decimal = Field(default=Decimal("10000000"), ge=0)
    max_net_notional_abs: Decimal = Field(default=Decimal("5000000"), ge=0)
    max_underlying_concentration_ratio: float = Field(default=0.6, gt=0, le=1)
    max_short_option_units: int = Field(default=5000, ge=0)


class RiskScoreWeights(BaseModel):
    margin: float = Field(default=1.0, ge=0)
    exposure: float = Field(default=1.0, ge=0)
    liquidity: float = Field(default=1.0, ge=0)
    volatility: float = Field(default=1.0, ge=0)
    portfolio_risk: float = Field(default=1.0, ge=0)
    concentration: float = Field(default=1.0, ge=0)
    time: float = Field(default=1.0, ge=0)
    event_risk: float = Field(default=1.0, ge=0)


class RiskSettings(BaseModel):
    enabled: bool = True
    block_on_kill_switch: bool = True
    warn_on_missing_market_data: bool = True
    position: RiskPositionSettings = Field(default_factory=RiskPositionSettings)
    margin: RiskMarginSettings = Field(default_factory=RiskMarginSettings)
    drawdown: RiskDrawdownSettings = Field(default_factory=RiskDrawdownSettings)
    greeks: RiskGreeksSettings = Field(default_factory=RiskGreeksSettings)
    liquidity: RiskLiquiditySettings = Field(default_factory=RiskLiquiditySettings)
    time: RiskTimeSettings = Field(default_factory=RiskTimeSettings)
    volatility: RiskVolatilitySettings = Field(default_factory=RiskVolatilitySettings)
    event: RiskEventSettings = Field(default_factory=RiskEventSettings)
    exposure: RiskExposureSettings = Field(default_factory=RiskExposureSettings)
    score_weights: RiskScoreWeights = Field(default_factory=RiskScoreWeights)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CEREMYN_",
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
    opportunities: OpportunitiesSettings = Field(default_factory=OpportunitiesSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    portfolio: PortfolioSettings = Field(default_factory=PortfolioSettings)

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

"""Settings and trading-mode gating tests.

These are the most important tests in M0: they pin down the safety defaults.
"""

import pytest
from pydantic import ValidationError

from ceremyn.config import Settings, TradingMode, get_settings


def make_settings(**overrides: object) -> Settings:
    """Build Settings isolated from the developer's real .env file."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class TestSafetyDefaults:
    def test_default_mode_is_research(self) -> None:
        assert make_settings().trading_mode is TradingMode.RESEARCH

    def test_live_trading_disabled_by_default(self) -> None:
        assert make_settings().live_trading_enabled is False

    def test_default_effective_mode_is_research(self) -> None:
        assert make_settings().effective_mode is TradingMode.RESEARCH


class TestEffectiveModeGating:
    def test_live_mode_without_config_gate_degrades_to_paper(self) -> None:
        settings = make_settings(trading_mode=TradingMode.LIVE)
        assert settings.effective_mode is TradingMode.PAPER

    def test_live_mode_with_config_gate_is_live(self) -> None:
        settings = make_settings(trading_mode=TradingMode.LIVE, live_trading_enabled=True)
        assert settings.effective_mode is TradingMode.LIVE

    def test_enabled_flag_alone_does_not_escalate_mode(self) -> None:
        for mode in (TradingMode.RESEARCH, TradingMode.PAPER):
            settings = make_settings(trading_mode=mode, live_trading_enabled=True)
            assert settings.effective_mode is mode

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(trading_mode="yolo")


class TestEnvironmentLoading:
    def test_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEREMYN_TRADING_MODE", "paper")
        assert make_settings().trading_mode is TradingMode.PAPER

    def test_nested_env_delimiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEREMYN_DB__HOST", "db.internal")
        monkeypatch.setenv("CEREMYN_DB__PORT", "6543")
        settings = make_settings()
        assert settings.db.host == "db.internal"
        assert settings.db.port == 6543


class TestConnectionUrls:
    def test_database_url(self) -> None:
        settings = make_settings()
        assert settings.db.url == ("postgresql+asyncpg://ceremyn:change-me@localhost:5432/ceremyn")

    def test_redis_url(self) -> None:
        assert make_settings().redis.url == "redis://localhost:6379/0"


class TestSecrets:
    def test_password_not_exposed_in_repr(self) -> None:
        settings = make_settings()
        assert "change-me" not in repr(settings.db)
        assert "change-me" not in str(settings.db.password)


class TestRuntimeSettings:
    def test_default_runtime_strategy_roster_is_explicit(self) -> None:
        settings = make_settings()
        assert settings.runtime.active_strategy_types == ("long_contrarian",)

    def test_runtime_strategy_roster_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "CEREMYN_RUNTIME__ACTIVE_STRATEGY_TYPES", '["long_contrarian", "long_skew"]'
        )
        settings = make_settings()
        assert settings.runtime.active_strategy_types == ("long_contrarian", "long_skew")


class TestRiskSettings:
    def test_risk_defaults_are_available(self) -> None:
        settings = make_settings()
        assert settings.risk.enabled is True
        assert settings.risk.margin.max_margin_usage_ratio == pytest.approx(0.8)
        assert settings.risk.time.trading_start.isoformat() == "09:15:00"

    def test_risk_thresholds_load_from_nested_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEREMYN_RISK__MARGIN__MAX_MARGIN_USAGE_RATIO", "0.65")
        monkeypatch.setenv("CEREMYN_RISK__TIME__ALLOW_EXPIRY_DAY", "true")
        settings = make_settings()
        assert settings.risk.margin.max_margin_usage_ratio == pytest.approx(0.65)
        assert settings.risk.time.allow_expiry_day is True


class TestOpportunitiesSettings:
    def test_scan_disabled_by_default(self) -> None:
        settings = make_settings()
        assert settings.opportunities.scan_enabled is False
        assert settings.opportunities.scan_all_equities is False

    def test_loads_from_nested_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CEREMYN_OPPORTUNITIES__SCAN_ENABLED", "true")
        monkeypatch.setenv("CEREMYN_OPPORTUNITIES__SCAN_ALL_EQUITIES", "true")
        monkeypatch.setenv("CEREMYN_OPPORTUNITIES__SCAN_INTERVAL_HOURS", "3")
        settings = make_settings()
        assert settings.opportunities.scan_enabled is True
        assert settings.opportunities.scan_all_equities is True
        assert settings.opportunities.scan_interval_hours == pytest.approx(3.0)


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()

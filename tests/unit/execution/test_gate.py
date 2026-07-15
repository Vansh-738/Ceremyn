from datetime import UTC, datetime

import pytest

from alphaquant.config import Settings, TradingMode
from alphaquant.core.exceptions import LiveTradingLockedError
from alphaquant.execution.gate import LiveTradingGate

T0 = datetime(2026, 7, 15, 4, 20, tzinfo=UTC)


def research_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def live_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, trading_mode=TradingMode.LIVE, live_trading_enabled=True
    )


def test_starts_disarmed() -> None:
    gate = LiveTradingGate()
    assert gate.is_armed is False
    assert gate.armed_at is None
    assert gate.permits_live_trading(research_settings()) is False
    assert gate.history() == ()


def test_arm_requires_gates_one_and_two_already_open() -> None:
    gate = LiveTradingGate()
    with pytest.raises(LiveTradingLockedError):
        gate.arm(settings=research_settings(), reason="attempt")
    assert gate.is_armed is False


def test_arm_requires_live_trading_enabled_even_with_live_mode() -> None:
    gate = LiveTradingGate()
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, trading_mode=TradingMode.LIVE, live_trading_enabled=False
    )
    with pytest.raises(LiveTradingLockedError):
        gate.arm(settings=settings, reason="attempt")


def test_arm_succeeds_when_gates_one_and_two_open() -> None:
    gate = LiveTradingGate()
    gate.arm(settings=live_settings(), reason="ops approved", at=T0)
    assert gate.is_armed is True
    assert gate.armed_at == T0
    assert gate.reason == "ops approved"


def test_permits_live_trading_requires_all_three_gates() -> None:
    gate = LiveTradingGate()
    settings = live_settings()
    assert gate.permits_live_trading(settings) is False  # gate 3 missing

    gate.arm(settings=settings, reason="ops approved")
    assert gate.permits_live_trading(settings) is True

    # Armed, but settings degrade (gate 2 closed) -> still not permitted.
    degraded = Settings(  # type: ignore[call-arg]
        _env_file=None, trading_mode=TradingMode.LIVE, live_trading_enabled=False
    )
    assert gate.permits_live_trading(degraded) is False

    # Armed, but research mode entirely -> still not permitted.
    assert gate.permits_live_trading(research_settings()) is False


def test_disarm_always_succeeds_and_resets_state() -> None:
    gate = LiveTradingGate()
    gate.arm(settings=live_settings(), reason="ops approved")
    gate.disarm(reason="end of day", at=T0)

    assert gate.is_armed is False
    assert gate.armed_at is None
    assert gate.reason == ""


def test_disarm_without_ever_arming_is_a_no_op() -> None:
    gate = LiveTradingGate()
    gate.disarm(reason="precaution")
    assert gate.is_armed is False
    assert len(gate.history()) == 1
    assert gate.history()[0].kind == "disarmed"


def test_history_records_arm_and_disarm() -> None:
    gate = LiveTradingGate()
    gate.arm(settings=live_settings(), reason="ops approved", at=T0)
    gate.disarm(reason="eod", at=T0)

    history = gate.history()
    assert [event.kind for event in history] == ["armed", "disarmed"]
    assert history[0].reason == "ops approved"
    assert history[1].reason == "eod"


def test_history_is_bounded() -> None:
    gate = LiveTradingGate(history_size=3)
    for _ in range(5):
        gate.disarm(reason="tick")
    assert len(gate.history()) == 3


def test_record_routing_appends_events() -> None:
    gate = LiveTradingGate()
    gate.record_routing(live=True, at=T0)
    gate.record_routing(live=False, at=T0)

    kinds = [event.kind for event in gate.history()]
    assert kinds == ["routed_live", "routed_fallback"]

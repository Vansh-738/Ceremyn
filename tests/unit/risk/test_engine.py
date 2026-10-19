from datetime import datetime
from decimal import Decimal

import pytest

from ceremyn.domain import (
    EquityInstrument,
    Exchange,
    KillSwitchState,
    PortfolioSnapshot,
    Side,
    Signal,
    SignalAction,
    SignalLeg,
)
from ceremyn.risk import (
    RiskConfigurationError,
    RiskEngine,
    RiskEvaluationError,
    build_default_rules,
)
from ceremyn.risk.context import RiskContext
from ceremyn.risk.models import RiskCategory, RuleResult
from ceremyn.risk.rules import RiskRule


def test_default_registry_contains_all_rules() -> None:
    assert len(build_default_rules()) == 16


def test_engine_approves_low_risk_signal(
    base_settings, portfolio, signal, utc_now: datetime
) -> None:
    base_settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    decision = RiskEngine(base_settings).evaluate(portfolio, signal, evaluated_at=utc_now)

    assert decision.approved is True
    assert 0.0 <= decision.risk_score <= 100.0
    assert decision.violations == ()


def test_engine_collects_failures_and_required_actions(
    base_settings, portfolio, signal, utc_now: datetime
) -> None:
    base_settings.risk.margin.max_margin_used = Decimal("120000")
    base_settings.risk.position.max_lots_per_signal = 1
    larger_signal = signal.model_copy(
        update={"legs": tuple(leg.model_copy(update={"lots": 2}) for leg in signal.legs)}
    )
    decision = RiskEngine(base_settings).validate(portfolio, larger_signal, evaluated_at=utc_now)

    assert decision.approved is False
    assert decision.required_actions
    assert any("margin" in violation for violation in decision.violations)


def test_engine_rejects_oversized_equity_using_real_notional(
    base_settings, utc_now: datetime
) -> None:
    """Regression: a zero-priced equity leg used to bypass every size limit."""
    base_settings.risk.exposure.max_gross_notional = Decimal("10000")
    base_settings.risk.exposure.max_underlying_concentration_ratio = 1.0
    equity = EquityInstrument(
        tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE"
    )
    signal = Signal(
        strategy_id="manual",
        created_at=utc_now,
        market_timestamp=utc_now,
        signal_type=SignalAction.ENTER,
        reason="oversized equity test",
        legs=(SignalLeg(contract=equity, side=Side.BUY, lots=10),),
        metadata={"reference_prices": {"RELIANCE": "1500"}},
    )

    decision = RiskEngine(base_settings).validate(
        portfolio=PortfolioSnapshot(), signal=signal, evaluated_at=utc_now
    )

    assert decision.approved is False
    assert any("gross notional" in violation for violation in decision.violations)


def test_engine_blocks_on_kill_switch(base_settings, portfolio, signal, utc_now: datetime) -> None:
    armed_portfolio = portfolio.model_copy(update={"kill_switch_state": KillSwitchState.TRIGGERED})
    decision = RiskEngine(base_settings).evaluate(armed_portfolio, signal, evaluated_at=utc_now)

    assert decision.approved is False
    assert "kill switch is triggered" in decision.violations


def test_engine_always_approves_exit_signals(
    base_settings, portfolio, signal, utc_now: datetime
) -> None:
    """An EXIT only closes/reduces an existing position -- it must never be blocked,
    even by a triggered kill switch or a limit the account is already breaching.
    (Regression: this exact gap trapped `long_strangle` in a losing position with no
    way to close it in a real-data backtest.)"""
    exit_signal = signal.model_copy(update={"signal_type": SignalAction.EXIT})
    armed_portfolio = portfolio.model_copy(update={"kill_switch_state": KillSwitchState.TRIGGERED})
    base_settings.risk.margin.max_margin_used = Decimal("1")  # impossible to clear

    engine = RiskEngine(base_settings)
    decision = engine.evaluate(armed_portfolio, exit_signal, evaluated_at=utc_now)

    assert decision.approved is True
    assert decision.violations == ()


def test_engine_returns_warning_when_disabled(
    base_settings, portfolio, signal, utc_now: datetime
) -> None:
    base_settings.risk.enabled = False
    decision = RiskEngine(base_settings).evaluate(portfolio, signal, evaluated_at=utc_now)

    assert decision.approved is True
    assert decision.warnings == ("risk engine disabled by configuration",)


def test_engine_rejects_zero_score_weights(base_settings) -> None:
    base_settings.risk.score_weights.margin = 0.0
    base_settings.risk.score_weights.exposure = 0.0
    base_settings.risk.score_weights.liquidity = 0.0
    base_settings.risk.score_weights.volatility = 0.0
    base_settings.risk.score_weights.portfolio_risk = 0.0
    base_settings.risk.score_weights.concentration = 0.0
    base_settings.risk.score_weights.time = 0.0
    base_settings.risk.score_weights.event_risk = 0.0

    with pytest.raises(RiskConfigurationError):
        RiskEngine(base_settings)


class BrokenRule(RiskRule):
    name = "Broken"
    category = RiskCategory.TIME

    def evaluate(self, context: RiskContext) -> RuleResult:
        raise RuntimeError("boom")


def test_engine_raises_on_rule_failure(base_settings, portfolio, signal, utc_now: datetime) -> None:
    engine = RiskEngine(base_settings, rules=(BrokenRule(),))

    with pytest.raises(RiskEvaluationError):
        engine.evaluate(portfolio, signal, evaluated_at=utc_now)

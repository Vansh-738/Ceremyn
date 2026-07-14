from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from alphaquant.domain import KillSwitchState, PortfolioSnapshot
from alphaquant.domain.enums import Side
from alphaquant.domain.signals import SignalLeg
from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskDecision
from alphaquant.risk.rules import utilization
from alphaquant.risk.rules.margin import MaximumMarginUsageRule
from alphaquant.risk.rules.time import ExpiryRestrictionsRule
from alphaquant.risk.rules.volatility import HighVolatilityFilterRule
from tests.unit.risk.conftest import make_contract, make_signal


def test_context_handles_zero_capital_and_metadata_collections(
    base_settings, ist_now, option_contract
) -> None:
    zero_portfolio = PortfolioSnapshot(
        buying_power=Decimal("0"),
        margin_used=Decimal("0"),
        kill_switch_state=KillSwitchState.TRIGGERED,
    )
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
        metadata={
            "projected_margin_used": Decimal("1"),
            "projected_exposure": {
                "gross_notional": "0",
                "net_notional": "0",
                "short_option_units": 0,
                "net_option_units": 0,
                "by_underlying": {},
            },
            "event_types": "RBI_POLICY",
            "liquidity_scores": {"leg-1": 0.8},
            "bid_ask_spread_ratios": {"leg-1": 0.01},
            "implied_volatility": False,
        },
    )

    context = RiskContext.from_inputs(
        portfolio=zero_portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert context.signal_short_option_units == 25
    assert context.has_kill_switch_block is True
    assert context.projected_margin_usage_ratio == 1.0
    assert context.underlying_concentration_ratio == 0.0
    assert context.event_types == ("RBI_POLICY",)
    assert context.liquidity_scores == (0.8,)
    assert context.bid_ask_spread_ratios == (0.01,)
    assert context.implied_volatility == 0.0


def test_context_rejects_naive_evaluated_at(base_settings, portfolio, signal) -> None:
    with pytest.raises(ValueError, match="evaluated_at must be timezone-aware"):
        RiskContext.from_inputs(
            portfolio=portfolio,
            signal=signal,
            configuration=base_settings,
            evaluated_at=datetime(2026, 7, 14, 10, 0),
        )


def test_risk_decision_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        RiskDecision(approved=True, risk_score=100.0, timestamp=datetime(2026, 7, 14, 10, 0))


def test_utilization_handles_zero_limits() -> None:
    assert utilization(0, 0) == 0.0
    assert utilization(1, 0) == 1.0


def test_margin_rule_fails_when_only_usage_ratio_is_breached(
    base_settings, ist_now, option_contract
) -> None:
    base_settings.risk.margin.max_margin_used = Decimal("100000")
    base_settings.risk.margin.max_margin_usage_ratio = 0.2
    portfolio = PortfolioSnapshot(buying_power=Decimal("100000"), margin_used=Decimal("0"))
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
        metadata={"margin_required": "50000"},
    )
    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    result = MaximumMarginUsageRule().evaluate(context)

    assert result.passed is False
    assert any("usage ratio" in violation for violation in result.violations)


def test_expiry_rule_enforces_minimum_days_to_expiry(base_settings, ist_now, portfolio) -> None:
    base_settings.risk.time.allow_expiry_day = True
    base_settings.risk.time.min_days_to_expiry = 2
    expiry = ist_now.date() + timedelta(days=1)
    signal = make_signal(
        created_at=ist_now,
        expiry=expiry,
        legs=(
            SignalLeg(
                contract=make_contract(symbol="NIFTY26JUL25000CE", expiry=expiry),
                side=Side.SELL,
                lots=1,
            ),
        ),
    )
    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert ExpiryRestrictionsRule().evaluate(context).passed is False


def test_volatility_rule_handles_missing_and_passing_metadata(
    base_settings, ist_now, portfolio, option_contract
) -> None:
    signal_missing = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
    )
    missing_context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal_missing,
        configuration=base_settings,
        evaluated_at=ist_now,
    )
    missing_result = HighVolatilityFilterRule().evaluate(missing_context)

    assert missing_result.passed is True
    assert missing_result.warnings

    signal_passing = signal_missing.model_copy(update={"metadata": {"volatility_percentile": 0.3}})
    passing_context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal_passing,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert HighVolatilityFilterRule().evaluate(passing_context).passed is True

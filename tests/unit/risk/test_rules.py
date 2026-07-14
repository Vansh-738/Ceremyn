from decimal import Decimal

import pytest

from alphaquant.domain.enums import Side
from alphaquant.domain.signals import SignalLeg
from alphaquant.risk.context import RiskContext
from alphaquant.risk.rules.drawdown import MaximumDailyLossRule, MaximumDrawdownRule
from alphaquant.risk.rules.event import EconomicEventFilterRule
from alphaquant.risk.rules.exposure import PortfolioExposureRule
from alphaquant.risk.rules.greeks import (
    MaximumDeltaRule,
    MaximumGammaRule,
    MaximumThetaRule,
    MaximumVegaRule,
)
from alphaquant.risk.rules.liquidity import BidAskSpreadCheckRule, LiquidityCheckRule
from alphaquant.risk.rules.margin import MaximumMarginUsageRule
from alphaquant.risk.rules.position import MaximumLotsRule, PositionLimitRule
from alphaquant.risk.rules.time import ExpiryRestrictionsRule, TradingHoursRule
from alphaquant.risk.rules.volatility import HighVolatilityFilterRule
from tests.unit.risk.conftest import make_contract, make_signal


def test_position_limit_rule_fails_on_projected_counts(
    base_settings, ist_now, portfolio, option_contract
) -> None:
    base_settings.risk.position.max_open_positions = 1
    base_settings.risk.position.max_positions_per_underlying = 1
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(
            SignalLeg(contract=option_contract, side=Side.BUY, lots=1),
            SignalLeg(
                contract=make_contract(
                    symbol="NIFTY26JUL25200CE",
                    strike="25200",
                    expiry=option_contract.expiry,
                ),
                side=Side.SELL,
                lots=1,
            ),
            SignalLeg(
                contract=make_contract(
                    symbol="NIFTY26JUL25300PE",
                    strike="25300",
                    expiry=option_contract.expiry,
                ),
                side=Side.BUY,
                lots=1,
            ),
        ),
    )
    result = PositionLimitRule().evaluate(
        RiskContext.from_inputs(
            portfolio=portfolio,
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
    )

    assert result.passed is False
    assert result.violations


def test_maximum_lots_rule_fails(base_settings, ist_now, option_contract, portfolio) -> None:
    base_settings.risk.position.max_lots_per_signal = 1
    signal = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=2),),
    )
    result = MaximumLotsRule().evaluate(
        RiskContext.from_inputs(
            portfolio=portfolio,
            signal=signal,
            configuration=base_settings,
            evaluated_at=ist_now,
        )
    )

    assert result.passed is False


def test_margin_and_drawdown_rules_fail(base_settings, ist_now, portfolio, signal) -> None:
    base_settings.risk.margin.max_margin_used = Decimal("120000")
    base_settings.risk.margin.max_margin_usage_ratio = 0.2
    base_settings.risk.drawdown.max_daily_loss = Decimal("100")
    base_settings.risk.drawdown.max_drawdown = Decimal("10000")
    stressed = portfolio.model_copy(
        update={"daily_pnl": Decimal("-2000"), "drawdown": Decimal("15000")}
    )
    context = RiskContext.from_inputs(
        portfolio=stressed,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert MaximumMarginUsageRule().evaluate(context).passed is False
    assert MaximumDailyLossRule().evaluate(context).passed is False
    assert MaximumDrawdownRule().evaluate(context).passed is False


@pytest.mark.parametrize(
    ("rule_cls", "field_name", "limit_field", "value"),
    [
        (MaximumDeltaRule, "delta", "max_abs_delta", 10.0),
        (MaximumGammaRule, "gamma", "max_abs_gamma", 1.0),
        (MaximumVegaRule, "vega", "max_abs_vega", 1.0),
        (MaximumThetaRule, "theta", "max_abs_theta", 1.0),
    ],
)
def test_greek_rules_fail_when_projected_limits_are_breached(
    base_settings,
    ist_now,
    portfolio,
    signal,
    rule_cls,
    field_name,
    limit_field,
    value,
) -> None:
    setattr(base_settings.risk.greeks, limit_field, value)
    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )
    result = rule_cls().evaluate(context)

    assert result.passed is False
    assert field_name in result.message


def test_liquidity_rules_handle_missing_and_breach_thresholds(
    base_settings,
    ist_now,
    portfolio,
    option_contract,
) -> None:
    signal_without_data = make_signal(
        created_at=ist_now,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
    )
    context_without = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal_without_data,
        configuration=base_settings,
        evaluated_at=ist_now,
    )
    liquidity_missing = LiquidityCheckRule().evaluate(context_without)
    spread_missing = BidAskSpreadCheckRule().evaluate(context_without)

    assert liquidity_missing.passed is True
    assert liquidity_missing.warnings
    assert spread_missing.passed is True
    assert spread_missing.warnings

    base_settings.risk.liquidity.min_liquidity_score = 0.5
    base_settings.risk.liquidity.max_bid_ask_spread_ratio = 0.01
    signal_bad = signal_without_data.model_copy(
        update={"metadata": {"liquidity_score": 0.2, "bid_ask_spread_ratio": 0.03}}
    )
    context_bad = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=signal_bad,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert LiquidityCheckRule().evaluate(context_bad).passed is False
    assert BidAskSpreadCheckRule().evaluate(context_bad).passed is False


def test_time_rules_fail_outside_trading_hours_and_on_restricted_expiry(
    base_settings,
    ist_now,
    portfolio,
    option_contract,
) -> None:
    outside_time = ist_now.replace(hour=8, minute=0)
    outside_signal = make_signal(
        created_at=outside_time,
        expiry=option_contract.expiry,
        legs=(SignalLeg(contract=option_contract, side=Side.SELL, lots=1),),
    )
    expiry_signal = make_signal(
        created_at=ist_now,
        expiry=ist_now.date(),
        legs=(
            SignalLeg(
                contract=make_contract(symbol="NIFTY26JUL25000CE", expiry=ist_now.date()),
                side=Side.SELL,
                lots=1,
            ),
        ),
    )
    trading_context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=outside_signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )
    expiry_context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=expiry_signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert TradingHoursRule().evaluate(trading_context).passed is False
    assert ExpiryRestrictionsRule().evaluate(expiry_context).passed is False


def test_volatility_event_and_exposure_rules_fail(
    base_settings, ist_now, portfolio, signal
) -> None:
    base_settings.risk.volatility.max_implied_volatility = 0.1
    base_settings.risk.volatility.max_volatility_percentile = 0.4
    base_settings.risk.exposure.max_gross_notional = Decimal("700000")
    base_settings.risk.exposure.max_net_notional_abs = Decimal("700000")
    base_settings.risk.exposure.max_underlying_concentration_ratio = 0.4
    base_settings.risk.exposure.max_short_option_units = 30
    event_signal = signal.model_copy(
        update={
            "metadata": {
                **signal.metadata,
                "has_high_impact_event": True,
                "event_types": ("RBI_POLICY",),
            }
        }
    )
    context = RiskContext.from_inputs(
        portfolio=portfolio,
        signal=event_signal,
        configuration=base_settings,
        evaluated_at=ist_now,
    )

    assert HighVolatilityFilterRule().evaluate(context).passed is False
    assert EconomicEventFilterRule().evaluate(context).passed is False
    assert PortfolioExposureRule().evaluate(context).passed is False

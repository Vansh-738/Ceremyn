"""Default risk-rule registry."""

from ceremyn.risk.rules import RiskRule
from ceremyn.risk.rules.drawdown import MaximumDailyLossRule, MaximumDrawdownRule
from ceremyn.risk.rules.event import EconomicEventFilterRule
from ceremyn.risk.rules.exposure import PortfolioExposureRule
from ceremyn.risk.rules.greeks import (
    MaximumDeltaRule,
    MaximumGammaRule,
    MaximumThetaRule,
    MaximumVegaRule,
)
from ceremyn.risk.rules.liquidity import BidAskSpreadCheckRule, LiquidityCheckRule
from ceremyn.risk.rules.margin import MaximumMarginUsageRule
from ceremyn.risk.rules.position import MaximumLotsRule, PositionLimitRule
from ceremyn.risk.rules.time import ExpiryRestrictionsRule, TradingHoursRule
from ceremyn.risk.rules.volatility import HighVolatilityFilterRule


def build_default_rules() -> tuple[RiskRule, ...]:
    return (
        PositionLimitRule(),
        MaximumLotsRule(),
        MaximumMarginUsageRule(),
        MaximumDailyLossRule(),
        MaximumDrawdownRule(),
        MaximumDeltaRule(),
        MaximumGammaRule(),
        MaximumVegaRule(),
        MaximumThetaRule(),
        LiquidityCheckRule(),
        BidAskSpreadCheckRule(),
        TradingHoursRule(),
        ExpiryRestrictionsRule(),
        HighVolatilityFilterRule(),
        EconomicEventFilterRule(),
        PortfolioExposureRule(),
    )

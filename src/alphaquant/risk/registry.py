"""Default risk-rule registry."""

from alphaquant.risk.rules import RiskRule
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

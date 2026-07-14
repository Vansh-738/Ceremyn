"""Time-based trading rules."""

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult
from alphaquant.risk.rules import RiskRule


class TradingHoursRule(RiskRule):
    name = "Trading Hours"
    category = RiskCategory.TIME

    def evaluate(self, context: RiskContext) -> RuleResult:
        market_time = context.market_time.timetz().replace(tzinfo=None)
        start = context.config.time.trading_start
        end = context.config.time.trading_end
        if market_time < start or market_time > end:
            return self.failed_result(
                risk_level=1.0,
                message="Signal is outside configured trading hours.",
                violations=(
                    "market time "
                    f"{market_time.isoformat()} is outside "
                    f"{start.isoformat()}-{end.isoformat()}",
                ),
                required_actions=("Submit the trade during configured market hours.",),
                details={"market_time": market_time.isoformat()},
            )
        return self.passed_result(
            risk_level=0.0,
            message="Signal was produced during configured trading hours.",
            details={"market_time": market_time.isoformat()},
        )


class ExpiryRestrictionsRule(RiskRule):
    name = "Expiry Restrictions"
    category = RiskCategory.TIME

    def evaluate(self, context: RiskContext) -> RuleResult:
        days_to_expiry = context.days_to_expiry
        min_days = context.config.time.min_days_to_expiry
        if days_to_expiry == 0 and not context.config.time.allow_expiry_day:
            return self.failed_result(
                risk_level=1.0,
                message="Expiry-day trading is disabled by configuration.",
                violations=(
                    "signal targets expiry-day contracts while expiry-day trading is disabled",
                ),
                required_actions=(
                    "Use a later expiry or enable expiry-day trading intentionally.",
                ),
                details={"days_to_expiry": days_to_expiry},
            )
        if days_to_expiry < min_days:
            return self.failed_result(
                risk_level=1.0,
                message="Signal breaches the minimum days-to-expiry requirement.",
                violations=(f"days to expiry {days_to_expiry} is below minimum {min_days}",),
                required_actions=("Trade a later expiry to meet the minimum holding horizon.",),
                details={"days_to_expiry": days_to_expiry},
            )
        return self.passed_result(
            risk_level=0.0 if days_to_expiry > min_days else 0.5,
            message="Signal satisfies expiry restrictions.",
            details={"days_to_expiry": days_to_expiry},
        )

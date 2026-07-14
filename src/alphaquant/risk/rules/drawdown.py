"""PnL and drawdown rules."""

from decimal import Decimal

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult
from alphaquant.risk.rules import RiskRule, utilization


class MaximumDailyLossRule(RiskRule):
    name = "Maximum Daily Loss"
    category = RiskCategory.PORTFOLIO_RISK

    def evaluate(self, context: RiskContext) -> RuleResult:
        loss = max(Decimal("0"), -context.portfolio.daily_pnl)
        limit = context.config.drawdown.max_daily_loss
        risk_level = utilization(loss, limit)
        if loss > limit:
            return self.failed_result(
                risk_level=risk_level,
                message="Portfolio daily loss has breached the configured limit.",
                violations=(f"daily loss {loss} exceeds limit {limit}",),
                required_actions=("Stop adding risk and reduce exposure for the day.",),
                details={"daily_loss": str(loss)},
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Portfolio daily loss is within the configured limit.",
            details={"daily_loss": str(loss)},
        )


class MaximumDrawdownRule(RiskRule):
    name = "Maximum Drawdown"
    category = RiskCategory.PORTFOLIO_RISK

    def evaluate(self, context: RiskContext) -> RuleResult:
        drawdown = context.portfolio.drawdown
        limit = context.config.drawdown.max_drawdown
        risk_level = utilization(drawdown, limit)
        if drawdown > limit:
            return self.failed_result(
                risk_level=risk_level,
                message="Portfolio drawdown has breached the configured limit.",
                violations=(f"drawdown {drawdown} exceeds limit {limit}",),
                required_actions=("Reduce risk and review the strategy before adding exposure.",),
                details={"drawdown": str(drawdown)},
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Portfolio drawdown is within the configured limit.",
            details={"drawdown": str(drawdown)},
        )

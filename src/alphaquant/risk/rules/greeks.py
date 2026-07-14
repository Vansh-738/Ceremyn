"""Portfolio greek-limit rules."""

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult
from alphaquant.risk.rules import RiskRule, utilization


class _BaseGreekRule(RiskRule):
    metric: str
    limit_field: str

    def evaluate(self, context: RiskContext) -> RuleResult:
        value = abs(getattr(context.projected_portfolio_greeks, self.metric))
        limit = float(getattr(context.config.greeks, self.limit_field))
        risk_level = utilization(value, limit)
        if value > limit:
            return self.failed_result(
                risk_level=risk_level,
                message=f"Projected portfolio {self.metric} breaches the configured limit.",
                violations=(f"absolute {self.metric} {value:.4f} exceeds limit {limit:.4f}",),
                required_actions=(f"Reduce {self.metric} exposure before placing this trade.",),
                details={self.metric: value},
            )
        return self.passed_result(
            risk_level=risk_level,
            message=f"Projected portfolio {self.metric} remains within limit.",
            details={self.metric: value},
        )


class MaximumDeltaRule(_BaseGreekRule):
    name = "Maximum Delta"
    category = RiskCategory.EXPOSURE
    metric = "delta"
    limit_field = "max_abs_delta"


class MaximumGammaRule(_BaseGreekRule):
    name = "Maximum Gamma"
    category = RiskCategory.PORTFOLIO_RISK
    metric = "gamma"
    limit_field = "max_abs_gamma"


class MaximumVegaRule(_BaseGreekRule):
    name = "Maximum Vega"
    category = RiskCategory.PORTFOLIO_RISK
    metric = "vega"
    limit_field = "max_abs_vega"


class MaximumThetaRule(_BaseGreekRule):
    name = "Maximum Theta"
    category = RiskCategory.PORTFOLIO_RISK
    metric = "theta"
    limit_field = "max_abs_theta"

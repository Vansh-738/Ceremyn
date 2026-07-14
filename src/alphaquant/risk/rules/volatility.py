"""Volatility rules."""

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult
from alphaquant.risk.rules import RiskRule, utilization


class HighVolatilityFilterRule(RiskRule):
    name = "High Volatility Filter"
    category = RiskCategory.VOLATILITY

    def evaluate(self, context: RiskContext) -> RuleResult:
        implied_volatility = context.implied_volatility
        percentile = context.volatility_percentile
        if implied_volatility is None and percentile is None:
            warnings = (
                ("volatility metadata missing from signal metadata",)
                if context.config.warn_on_missing_market_data
                else ()
            )
            return self.passed_result(
                risk_level=0.5 if warnings else 0.0,
                message="Volatility metadata unavailable.",
                warnings=warnings,
            )

        risk_levels: list[float] = []
        violations: list[str] = []
        actions: list[str] = []
        if implied_volatility is not None:
            iv_limit = context.config.volatility.max_implied_volatility
            risk_levels.append(utilization(implied_volatility, iv_limit))
            if implied_volatility > iv_limit:
                violations.append(
                    f"implied volatility {implied_volatility:.4f} exceeds limit {iv_limit:.4f}"
                )
                actions.append("Wait for volatility to normalize or reduce exposure.")
        if percentile is not None:
            percentile_limit = context.config.volatility.max_volatility_percentile
            risk_levels.append(utilization(percentile, percentile_limit))
            if percentile > percentile_limit:
                violations.append(
                    f"volatility percentile {percentile:.4f} exceeds limit {percentile_limit:.4f}"
                )
                actions.append("Avoid adding risk in the current volatility regime.")

        risk_level = max(risk_levels, default=0.0)
        if violations:
            return self.failed_result(
                risk_level=risk_level,
                message="Signal fails configured volatility filters.",
                violations=tuple(violations),
                required_actions=tuple(actions),
                details={
                    "implied_volatility": implied_volatility,
                    "volatility_percentile": percentile,
                },
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Signal satisfies configured volatility filters.",
            details={
                "implied_volatility": implied_volatility,
                "volatility_percentile": percentile,
            },
        )

"""Margin-usage rules."""

from ceremyn.risk.context import RiskContext
from ceremyn.risk.models import RiskCategory, RuleResult
from ceremyn.risk.rules import RiskRule, utilization


class MaximumMarginUsageRule(RiskRule):
    name = "Maximum Margin Usage"
    category = RiskCategory.MARGIN

    def evaluate(self, context: RiskContext) -> RuleResult:
        margin_limit = context.config.margin.max_margin_used
        ratio_limit = context.config.margin.max_margin_usage_ratio
        projected_margin = context.projected_margin_used
        projected_ratio = context.projected_margin_usage_ratio
        risk_level = max(
            utilization(projected_margin, margin_limit),
            utilization(projected_ratio, ratio_limit),
        )

        violations: list[str] = []
        actions: list[str] = []
        if projected_margin > margin_limit:
            violations.append(
                f"projected margin used {projected_margin} exceeds limit {margin_limit}"
            )
            actions.append("Reduce order size or free capital before trading.")
        if projected_ratio > ratio_limit:
            violations.append(
                "projected margin usage ratio "
                f"{projected_ratio:.4f} exceeds limit {ratio_limit:.4f}"
            )
            actions.append("Lower leverage to remain below the margin usage ratio.")

        if violations:
            return self.failed_result(
                risk_level=risk_level,
                message="Projected margin usage breaches configured thresholds.",
                violations=tuple(violations),
                required_actions=tuple(actions),
                details={
                    "projected_margin_used": str(projected_margin),
                    "projected_margin_usage_ratio": projected_ratio,
                },
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Projected margin usage remains within limits.",
            details={
                "projected_margin_used": str(projected_margin),
                "projected_margin_usage_ratio": projected_ratio,
            },
        )

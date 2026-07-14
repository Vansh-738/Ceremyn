"""Portfolio exposure and concentration rules."""

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult
from alphaquant.risk.rules import RiskRule, utilization


class PortfolioExposureRule(RiskRule):
    name = "Portfolio Exposure"
    category = RiskCategory.EXPOSURE

    def evaluate(self, context: RiskContext) -> RuleResult:
        exposure = context.projected_exposure
        gross_limit = context.config.exposure.max_gross_notional
        net_limit = context.config.exposure.max_net_notional_abs
        concentration_limit = context.config.exposure.max_underlying_concentration_ratio
        short_limit = context.config.exposure.max_short_option_units

        gross_ratio = utilization(exposure.gross_notional, gross_limit)
        net_ratio = utilization(abs(exposure.net_notional), net_limit)
        concentration_ratio = utilization(
            context.underlying_concentration_ratio,
            concentration_limit,
        )
        short_ratio = utilization(exposure.short_option_units, short_limit)
        risk_level = max(gross_ratio, net_ratio, concentration_ratio, short_ratio)

        violations: list[str] = []
        actions: list[str] = []
        if exposure.gross_notional > gross_limit:
            violations.append(
                f"gross notional {exposure.gross_notional} exceeds limit {gross_limit}"
            )
            actions.append("Reduce gross exposure before submitting the trade.")
        if abs(exposure.net_notional) > net_limit:
            violations.append(
                f"absolute net notional {abs(exposure.net_notional)} exceeds limit {net_limit}"
            )
            actions.append("Reduce directional exposure before submitting the trade.")
        if context.underlying_concentration_ratio > concentration_limit:
            violations.append(
                "underlying concentration ratio "
                f"{context.underlying_concentration_ratio:.4f} exceeds "
                f"limit {concentration_limit:.4f}"
            )
            actions.append("Diversify exposure across underlyings before trading.")
        if exposure.short_option_units > short_limit:
            violations.append(
                f"short option units {exposure.short_option_units} exceed limit {short_limit}"
            )
            actions.append("Reduce short option size before trading.")

        if violations:
            return self.failed_result(
                risk_level=risk_level,
                message="Projected portfolio exposure breaches configured limits.",
                violations=tuple(violations),
                required_actions=tuple(actions),
                details={
                    "gross_notional": str(exposure.gross_notional),
                    "net_notional": str(exposure.net_notional),
                    "underlying_concentration_ratio": context.underlying_concentration_ratio,
                    "short_option_units": exposure.short_option_units,
                },
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Projected portfolio exposure remains within limits.",
            details={
                "gross_notional": str(exposure.gross_notional),
                "net_notional": str(exposure.net_notional),
                "underlying_concentration_ratio": context.underlying_concentration_ratio,
                "short_option_units": exposure.short_option_units,
            },
        )

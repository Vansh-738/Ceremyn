"""Position and lot-size rules."""

from ceremyn.risk.context import RiskContext
from ceremyn.risk.models import RiskCategory, RuleResult
from ceremyn.risk.rules import RiskRule, utilization


class PositionLimitRule(RiskRule):
    name = "Position Limit"
    category = RiskCategory.CONCENTRATION

    def evaluate(self, context: RiskContext) -> RuleResult:
        max_open = context.config.position.max_open_positions
        max_underlying = context.config.position.max_positions_per_underlying
        open_ratio = utilization(context.projected_open_positions, max_open)
        underlying_ratio = utilization(
            context.projected_open_positions_in_underlying,
            max_underlying,
        )
        risk_level = max(open_ratio, underlying_ratio)
        violations: list[str] = []
        actions: list[str] = []

        if context.projected_open_positions > max_open:
            violations.append(
                f"projected open positions {context.projected_open_positions} "
                f"exceed limit {max_open}"
            )
            actions.append("Reduce overall open positions before placing this signal.")
        if context.projected_open_positions_in_underlying > max_underlying:
            violations.append(
                "projected underlying position count "
                f"{context.projected_open_positions_in_underlying} exceeds limit {max_underlying}"
            )
            actions.append("Reduce concentration in the underlying before placing this signal.")

        if violations:
            return self.failed_result(
                risk_level=risk_level,
                message="Projected position count breaches configured limits.",
                violations=tuple(violations),
                required_actions=tuple(actions),
                details={
                    "projected_open_positions": context.projected_open_positions,
                    "projected_open_positions_in_underlying": (
                        context.projected_open_positions_in_underlying
                    ),
                },
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Projected position counts remain within configured limits.",
            details={
                "projected_open_positions": context.projected_open_positions,
                "projected_open_positions_in_underlying": (
                    context.projected_open_positions_in_underlying
                ),
            },
        )


class MaximumLotsRule(RiskRule):
    name = "Maximum Lots"
    category = RiskCategory.CONCENTRATION

    def evaluate(self, context: RiskContext) -> RuleResult:
        limit = context.config.position.max_lots_per_signal
        lots = context.signal_lots_total
        risk_level = utilization(lots, limit)
        if lots > limit:
            return self.failed_result(
                risk_level=risk_level,
                message="Signal exceeds maximum lots per trade.",
                violations=(f"signal lots {lots} exceed limit {limit}",),
                required_actions=("Reduce lots in the signal before resubmitting.",),
                details={"signal_lots_total": lots},
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Signal lot size is within the configured limit.",
            details={"signal_lots_total": lots},
        )

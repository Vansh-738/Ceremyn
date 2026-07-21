"""Liquidity and spread rules."""

from ceremyn.risk.context import RiskContext
from ceremyn.risk.models import RiskCategory, RuleResult
from ceremyn.risk.rules import RiskRule, utilization


class LiquidityCheckRule(RiskRule):
    name = "Liquidity Check"
    category = RiskCategory.LIQUIDITY

    def evaluate(self, context: RiskContext) -> RuleResult:
        scores = context.liquidity_scores
        if not scores:
            warnings = (
                ("liquidity scores missing from signal metadata",)
                if context.config.warn_on_missing_market_data
                else ()
            )
            return self.passed_result(
                risk_level=0.5 if warnings else 0.0,
                message="Liquidity metadata unavailable.",
                warnings=warnings,
            )

        min_score = min(scores)
        threshold = context.config.liquidity.min_liquidity_score
        risk_level = max(0.0, min(1.0, 1.0 - min_score))
        if min_score < threshold:
            return self.failed_result(
                risk_level=risk_level,
                message="Signal fails the minimum liquidity requirement.",
                violations=(f"minimum liquidity score {min_score:.4f} is below {threshold:.4f}",),
                required_actions=("Trade a more liquid contract or reduce size.",),
                details={"minimum_liquidity_score": min_score},
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Signal meets the minimum liquidity requirement.",
            details={"minimum_liquidity_score": min_score},
        )


class BidAskSpreadCheckRule(RiskRule):
    name = "Bid Ask Spread Check"
    category = RiskCategory.LIQUIDITY

    def evaluate(self, context: RiskContext) -> RuleResult:
        ratios = context.bid_ask_spread_ratios
        if not ratios:
            warnings = (
                ("bid/ask spread ratios missing from signal metadata",)
                if context.config.warn_on_missing_market_data
                else ()
            )
            return self.passed_result(
                risk_level=0.5 if warnings else 0.0,
                message="Spread metadata unavailable.",
                warnings=warnings,
            )

        max_ratio = max(ratios)
        threshold = context.config.liquidity.max_bid_ask_spread_ratio
        risk_level = utilization(max_ratio, threshold)
        if max_ratio > threshold:
            return self.failed_result(
                risk_level=risk_level,
                message="Signal breaches the maximum bid/ask spread threshold.",
                violations=(
                    f"maximum bid/ask spread ratio {max_ratio:.4f} exceeds {threshold:.4f}",
                ),
                required_actions=("Wait for spreads to tighten or choose a more liquid contract.",),
                details={"maximum_bid_ask_spread_ratio": max_ratio},
            )
        return self.passed_result(
            risk_level=risk_level,
            message="Signal spread remains within threshold.",
            details={"maximum_bid_ask_spread_ratio": max_ratio},
        )

"""Event-driven risk rules."""

from ceremyn.risk.context import RiskContext
from ceremyn.risk.models import RiskCategory, RuleResult
from ceremyn.risk.rules import RiskRule


class EconomicEventFilterRule(RiskRule):
    name = "Economic Event Filter"
    category = RiskCategory.EVENT_RISK

    def evaluate(self, context: RiskContext) -> RuleResult:
        blocked_types = set(context.config.event.blocked_event_types)
        matching_types = tuple(
            event_type for event_type in context.event_types if event_type in blocked_types
        )

        violations: list[str] = []
        if context.config.event.block_on_high_impact and context.has_high_impact_event:
            violations.append("signal overlaps a high-impact event window")
        if matching_types:
            violations.append(f"blocked event types present: {', '.join(matching_types)}")

        if violations:
            return self.failed_result(
                risk_level=1.0,
                message="Signal is blocked by event-risk filters.",
                violations=tuple(violations),
                required_actions=("Wait until the event window has passed before trading.",),
                details={"event_types": context.event_types},
            )
        return self.passed_result(
            risk_level=0.0,
            message="Signal passes event-risk filters.",
            details={"event_types": context.event_types},
        )

"""Risk rule interfaces and helpers."""

from abc import ABC, abstractmethod
from decimal import Decimal

from alphaquant.risk.context import RiskContext
from alphaquant.risk.models import RiskCategory, RuleResult


def utilization(value: Decimal | float | int, limit: Decimal | float | int) -> float:
    numeric_limit = float(limit)
    numeric_value = float(value)
    if numeric_limit <= 0:
        return 1.0 if numeric_value > 0 else 0.0
    return max(0.0, min(1.0, numeric_value / numeric_limit))


class RiskRule(ABC):
    name: str
    category: RiskCategory
    blocking: bool = True

    @abstractmethod
    def evaluate(self, context: RiskContext) -> RuleResult:
        """Evaluate the rule against the provided context."""

    def passed_result(
        self,
        *,
        risk_level: float = 0.0,
        message: str = "",
        warnings: tuple[str, ...] = (),
        details: dict[str, object] | None = None,
    ) -> RuleResult:
        return RuleResult(
            name=self.name,
            category=self.category,
            passed=True,
            blocking=self.blocking,
            risk_level=risk_level,
            message=message,
            warnings=warnings,
            details=details or {},
        )

    def failed_result(
        self,
        *,
        risk_level: float = 1.0,
        message: str,
        violations: tuple[str, ...],
        required_actions: tuple[str, ...],
        details: dict[str, object] | None = None,
    ) -> RuleResult:
        return RuleResult(
            name=self.name,
            category=self.category,
            passed=False,
            blocking=self.blocking,
            risk_level=risk_level,
            message=message,
            violations=violations,
            required_actions=required_actions,
            details=details or {},
        )


__all__ = ["RiskRule", "utilization"]

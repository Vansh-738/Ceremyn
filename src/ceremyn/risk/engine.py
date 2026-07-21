"""Risk engine orchestration."""

from datetime import datetime

from ceremyn.config import RiskSettings, Settings
from ceremyn.core.timeutils import now_utc
from ceremyn.domain import PortfolioSnapshot, Signal
from ceremyn.domain.enums import KillSwitchState, SignalAction
from ceremyn.risk.context import RiskContext
from ceremyn.risk.exceptions import RiskConfigurationError, RiskEvaluationError
from ceremyn.risk.models import RiskCategory, RiskDecision, RuleResult
from ceremyn.risk.registry import build_default_rules
from ceremyn.risk.rules import RiskRule


class RiskEngine:
    """Evaluate a signal against the current portfolio and configured rules."""

    def __init__(
        self,
        configuration: RiskSettings | Settings,
        *,
        rules: tuple[RiskRule, ...] | None = None,
    ) -> None:
        self.configuration = configuration
        self.config = configuration.risk if isinstance(configuration, Settings) else configuration
        self.rules = rules or build_default_rules()
        self._validate_score_weights()

    def _validate_score_weights(self) -> None:
        weights = tuple(float(value) for value in self.config.score_weights.model_dump().values())
        if sum(weights) <= 0:
            raise RiskConfigurationError("risk score weights must sum to a positive value")

    def evaluate(
        self,
        portfolio: PortfolioSnapshot,
        signal: Signal,
        *,
        evaluated_at: datetime | None = None,
    ) -> RiskDecision:
        timestamp = evaluated_at or now_utc()
        # An EXIT only ever closes/reduces an existing position -- it can't create new
        # risk, so nothing (including a triggered kill switch) should be able to trap
        # a strategy holding a position it can no longer close. ADJUST is not exempt:
        # rolling a strike can still change margin/exposure, so it goes through the
        # normal checks below like ENTER does.
        if signal.signal_type is SignalAction.EXIT:
            return RiskDecision(
                approved=True,
                risk_score=0.0,
                warnings=("risk checks bypassed: exit signal always allowed to close risk",),
                timestamp=timestamp,
            )
        context = RiskContext.from_inputs(
            portfolio=portfolio,
            signal=signal,
            configuration=self.configuration,
            evaluated_at=timestamp,
        )
        rule_results: list[RuleResult] = []

        if (
            self.config.block_on_kill_switch
            and portfolio.kill_switch_state is KillSwitchState.TRIGGERED
        ):
            rule_results.append(
                RuleResult(
                    name="Kill Switch",
                    category=RiskCategory.PORTFOLIO_RISK,
                    passed=False,
                    blocking=True,
                    risk_level=1.0,
                    message="Portfolio kill switch is triggered.",
                    violations=("kill switch is triggered",),
                    required_actions=("Disarm the kill switch only after manual review.",),
                )
            )

        if not self.config.enabled:
            return RiskDecision(
                approved=True,
                risk_score=100.0,
                warnings=("risk engine disabled by configuration",),
                rule_results=tuple(rule_results),
                timestamp=timestamp,
            )

        for rule in self.rules:
            try:
                rule_results.append(rule.evaluate(context))
            except Exception as exc:  # pragma: no cover - exercised in failure test
                raise RiskEvaluationError(f"rule {rule.name} failed during evaluation") from exc

        return self._build_decision(timestamp=timestamp, rule_results=tuple(rule_results))

    def validate(
        self,
        portfolio: PortfolioSnapshot,
        signal: Signal,
        *,
        evaluated_at: datetime | None = None,
    ) -> RiskDecision:
        return self.evaluate(portfolio, signal, evaluated_at=evaluated_at)

    def _build_decision(
        self,
        *,
        timestamp: datetime,
        rule_results: tuple[RuleResult, ...],
    ) -> RiskDecision:
        approved = all(result.passed or not result.blocking for result in rule_results)
        violations = tuple(violation for result in rule_results for violation in result.violations)
        warnings = tuple(warning for result in rule_results for warning in result.warnings)
        required_actions = tuple(
            action for result in rule_results for action in result.required_actions
        )
        return RiskDecision(
            approved=approved,
            risk_score=self._calculate_risk_score(rule_results),
            violations=violations,
            warnings=warnings,
            required_actions=required_actions,
            rule_results=rule_results,
            timestamp=timestamp,
        )

    def _calculate_risk_score(self, rule_results: tuple[RuleResult, ...]) -> float:
        category_risk = {category.value: 0.0 for category in RiskCategory}
        for result in rule_results:
            key = result.category.value
            category_risk[key] = max(category_risk[key], result.risk_level)

        weights = {
            name: float(value) for name, value in self.config.score_weights.model_dump().items()
        }
        total_weight = sum(weights.values())
        weighted_risk = sum(category_risk[name] * weight for name, weight in weights.items())
        score = (1.0 - (weighted_risk / total_weight)) * 100.0
        return max(0.0, min(100.0, round(score, 2)))

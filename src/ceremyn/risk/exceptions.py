"""Risk engine exceptions."""


class RiskEngineError(Exception):
    """Base class for risk-engine errors."""


class RiskConfigurationError(RiskEngineError):
    """Raised when risk configuration is invalid."""


class RiskEvaluationError(RiskEngineError):
    """Raised when rule evaluation fails unexpectedly."""

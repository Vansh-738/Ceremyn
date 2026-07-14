"""Order management system."""

from alphaquant.oms.broker import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPositionSnapshot,
    BrokerSubmissionResult,
)
from alphaquant.oms.engine import OMSKillSwitch, OrderManagementEngine
from alphaquant.oms.events import OMSEvent, OMSEventType
from alphaquant.oms.exceptions import (
    OMSBrokerCapabilityError,
    OMSDuplicateRequestError,
    OMSError,
    OMSKillSwitchActiveError,
    OMSNonRetryableBrokerError,
    OMSRetryableError,
    OMSRiskRejectedError,
    OMSStateError,
    OMSValidationError,
)
from alphaquant.oms.executor import BrokerExecutor, ExecutorResult
from alphaquant.oms.fills import FillProcessor
from alphaquant.oms.idempotency import InMemoryIdempotencyStore
from alphaquant.oms.journal import InMemoryJournalStore, JSONJournalStore, OMSJournal
from alphaquant.oms.ledger import LedgerEntry, LedgerEntryKind, OMSLedger
from alphaquant.oms.metrics import OMSMetrics, OMSMetricsSnapshot
from alphaquant.oms.orders import (
    CancelOrderCommand,
    ExecutionStyle,
    OMSExecutionState,
    OMSOrder,
    OrderIntent,
    OrderPlan,
    OrderPlanner,
    PlannedOrder,
    PlanOrderRole,
    ReplaceOrderCommand,
    SubmitOrderCommand,
)
from alphaquant.oms.positions import OMSPortfolio
from alphaquant.oms.reconciliation import OMSReconciler, ReconciliationReport
from alphaquant.oms.retry import RetryDecision, RetryPolicy
from alphaquant.oms.router import BrokerRouter
from alphaquant.oms.validators import OMSValidator

__all__ = [
    "BrokerAdapter",
    "BrokerCapabilities",
    "BrokerCashSnapshot",
    "BrokerExecutionReport",
    "BrokerExecutor",
    "BrokerOrderSnapshot",
    "BrokerOrderStatus",
    "BrokerPositionSnapshot",
    "BrokerRouter",
    "BrokerSubmissionResult",
    "CancelOrderCommand",
    "ExecutionStyle",
    "ExecutorResult",
    "FillProcessor",
    "InMemoryIdempotencyStore",
    "InMemoryJournalStore",
    "JSONJournalStore",
    "LedgerEntry",
    "LedgerEntryKind",
    "OMSBrokerCapabilityError",
    "OMSDuplicateRequestError",
    "OMSEngine",
    "OMSError",
    "OMSEvent",
    "OMSEventType",
    "OMSExecutionState",
    "OMSJournal",
    "OMSKillSwitch",
    "OMSKillSwitchActiveError",
    "OMSLedger",
    "OMSMetrics",
    "OMSMetricsSnapshot",
    "OMSNonRetryableBrokerError",
    "OMSOrder",
    "OMSPortfolio",
    "OMSReconciler",
    "OMSRetryableError",
    "OMSRiskRejectedError",
    "OMSStateError",
    "OMSValidationError",
    "OMSValidator",
    "OrderIntent",
    "OrderManagementEngine",
    "OrderPlan",
    "OrderPlanner",
    "PlanOrderRole",
    "PlannedOrder",
    "ReconciliationReport",
    "ReplaceOrderCommand",
    "RetryDecision",
    "RetryPolicy",
    "SubmitOrderCommand",
]

OMSEngine = OrderManagementEngine

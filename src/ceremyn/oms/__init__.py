"""Order management system."""

from ceremyn.oms.broker import (
    BrokerAdapter,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPositionSnapshot,
    BrokerSubmissionResult,
)
from ceremyn.oms.engine import OMSKillSwitch, OrderManagementEngine
from ceremyn.oms.events import OMSEvent, OMSEventType
from ceremyn.oms.exceptions import (
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
from ceremyn.oms.executor import BrokerExecutor, ExecutorResult
from ceremyn.oms.fills import FillProcessor
from ceremyn.oms.idempotency import InMemoryIdempotencyStore
from ceremyn.oms.journal import InMemoryJournalStore, JSONJournalStore, OMSJournal
from ceremyn.oms.ledger import LedgerEntry, LedgerEntryKind, OMSLedger
from ceremyn.oms.metrics import OMSMetrics, OMSMetricsSnapshot
from ceremyn.oms.orders import (
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
from ceremyn.oms.positions import OMSPortfolio
from ceremyn.oms.reconciliation import OMSReconciler, ReconciliationReport
from ceremyn.oms.retry import RetryDecision, RetryPolicy
from ceremyn.oms.router import BrokerRouter
from ceremyn.oms.validators import OMSValidator

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

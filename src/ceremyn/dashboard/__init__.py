"""Ceremyn Dashboard & Observability — a read-only view over existing system state.

The dashboard visualizes state from the Feature Store, Research Lab, OMS, Paper Trading,
Risk Engine, Live Engine, and Portfolio. It contains no business logic, exposes only
read-only APIs + a WebSocket, and can never place an order or bypass the OMS — it depends
on read-only port protocols, not on the concrete engines.
"""

from ceremyn.dashboard.api import (
    build_dashboard_router,
    create_dashboard_app,
    run_broadcaster,
)
from ceremyn.dashboard.backend import (
    DashboardService,
    DashboardSources,
    FeatureSource,
    KillSwitchStatus,
    LiveSource,
    LogSource,
    OMSSource,
    PaperSource,
    PortfolioSource,
    ResearchSource,
    RiskSource,
)
from ceremyn.dashboard.config import DashboardSettings
from ceremyn.dashboard.events import EventBridge, SnapshotDiffer
from ceremyn.dashboard.models import Alert, AlertsView, Channel, MetricsView, OverviewView
from ceremyn.dashboard.permissions import Permission, Role
from ceremyn.dashboard.websocket import ConnectionManager, broadcast_changes

__all__ = [
    "Alert",
    "AlertsView",
    "Channel",
    "ConnectionManager",
    "DashboardService",
    "DashboardSettings",
    "DashboardSources",
    "EventBridge",
    "FeatureSource",
    "KillSwitchStatus",
    "LiveSource",
    "LogSource",
    "MetricsView",
    "OMSSource",
    "OverviewView",
    "PaperSource",
    "Permission",
    "PortfolioSource",
    "ResearchSource",
    "RiskSource",
    "Role",
    "SnapshotDiffer",
    "broadcast_changes",
    "build_dashboard_router",
    "create_dashboard_app",
    "run_broadcaster",
]

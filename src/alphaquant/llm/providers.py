"""Read-only provider Protocols — the only way data reaches the assistant.

`DashboardReader` is a structural mirror of `dashboard.backend.DashboardService`'s public
surface. `llm` never imports `dashboard.backend` (it transitively reaches `alphaquant.risk`);
instead, the composition root (`api/`) hands over the *real*, already-built `DashboardService`
instance, which satisfies this Protocol by duck typing. The two other Protocols cover the
small gaps nothing else already exposes (see `llm/snapshots.py`).
"""

from typing import Protocol

from alphaquant.dashboard.models import (
    AlertsView,
    FeatureStoreView,
    LiveMarketView,
    OMSView,
    OrdersView,
    OverviewView,
    PaperView,
    PortfolioView,
    PositionsView,
    ResearchView,
    RiskView,
)
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief


class DashboardReader(Protocol):
    """Everything the dashboard itself can see — the assistant reads through the exact same
    door, so its answers can never disagree with what's on screen."""

    def overview(self) -> OverviewView: ...
    def portfolio(self) -> PortfolioView: ...
    def positions(self) -> PositionsView: ...
    def orders(self, *, page: int = 1, page_size: int | None = None) -> OrdersView: ...
    def live(self) -> LiveMarketView: ...
    def features(self) -> FeatureStoreView: ...
    def risk(self) -> RiskView: ...
    def oms(self) -> OMSView: ...
    def research(self) -> ResearchView: ...
    def paper(self) -> PaperView: ...
    def alerts(self) -> AlertsView: ...


class ExperimentDetailReader(Protocol):
    def detail(self, experiment_id: str) -> ExperimentDetailBrief | None: ...


class RecapReader(Protocol):
    def daily(self) -> RecapBrief: ...
    def session(self) -> RecapBrief: ...

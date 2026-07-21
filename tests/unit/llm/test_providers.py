"""`DashboardReader` is never implemented directly — it's satisfied by the real
`DashboardService` via duck typing. These tests prove that actually works (not just that it
type-checks), using the dashboard test suite's own fixtures so the coverage is against
realistic, fully-populated data.
"""

from ceremyn.dashboard.backend import DashboardService, DashboardSources
from ceremyn.llm.providers import DashboardReader
from ceremyn.oms.orders import OMSExecutionState
from tests.unit.dashboard.conftest import (
    FakeFeatures,
    FakeLive,
    FakeOMS,
    FakePaper,
    FakePortfolio,
    FakeResearch,
    FakeRisk,
    make_oms_order,
    make_portfolio_snapshot,
    make_risk_decision,
)


def make_reader() -> DashboardReader:
    sources = DashboardSources(
        live=FakeLive(),
        oms=FakeOMS(
            orders=(
                make_oms_order(state=OMSExecutionState.PENDING),
                make_oms_order(state=OMSExecutionState.FILLED, filled=25),
            ),
            portfolio=make_portfolio_snapshot(),
        ),
        portfolio=FakePortfolio(make_portfolio_snapshot()),
        risk=FakeRisk((make_risk_decision(approved=True),)),
        features=FakeFeatures(),
        paper=FakePaper(),
        research=FakeResearch(),
    )
    return DashboardService(sources)


def test_dashboard_service_satisfies_every_reader_method() -> None:
    reader = make_reader()
    assert reader.overview().open_orders == 1
    assert reader.portfolio() is not None
    assert reader.positions() is not None
    assert reader.orders().total >= 1
    assert reader.live() is not None
    assert reader.features() is not None
    assert reader.risk().decisions
    assert reader.oms() is not None
    assert reader.research() is not None
    assert reader.paper() is not None
    assert reader.alerts() is not None


def test_orders_paging_is_forwarded() -> None:
    reader = make_reader()
    page = reader.orders(page=1, page_size=1)
    assert page.page == 1
    assert page.page_size == 1
    assert len(page.orders) <= 1


def test_empty_dashboard_service_still_satisfies_the_protocol() -> None:
    reader: DashboardReader = DashboardService(DashboardSources())
    assert reader.overview().open_orders == 0
    assert reader.risk().decisions == ()
    assert reader.research().experiment_count == 0

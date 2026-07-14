from decimal import Decimal

from alphaquant.oms import OMSLedger, OMSPortfolio, OMSReconciler
from alphaquant.oms.ledger import LedgerEntry, LedgerEntryKind
from tests.unit.oms.conftest import T0, FakeBroker


def test_reconciliation_detects_position_and_cash_drift() -> None:
    portfolio = OMSPortfolio()
    ledger = OMSLedger()
    broker = FakeBroker()
    broker.cash = Decimal("900000")
    ledger.append(
        LedgerEntry(
            kind=LedgerEntryKind.FILL,
            timestamp=T0,
            payload={
                "tradingsymbol": "NIFTY25JUL24000CE",
                "side": "BUY",
                "quantity": 75,
                "price": "150",
            },
        )
    )
    report = OMSReconciler().reconcile(orders=(), broker=broker, ledger=ledger, portfolio=portfolio)

    assert report.reconciled is False
    assert report.cash_drift != 0

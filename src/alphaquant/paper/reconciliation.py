"""Reconciliation: prove the portfolio matches the applied fills.

An independent safety check: recompute the net signed quantity per instrument from the
fill log and compare it against the portfolio's positions. Any mismatch is drift and is
reported per symbol — a paper session should always reconcile cleanly.
"""

from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.fills import VirtualFill
from alphaquant.domain.enums import Side
from alphaquant.paper.portfolio import PaperPortfolio


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    reconciled: bool
    drift: dict[str, int] = {}  # tradingsymbol -> (portfolio_qty - expected_qty)

    @property
    def drift_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.drift))


class Reconciler:
    def __init__(self) -> None:
        self._expected: dict[str, int] = {}

    def record_fill(self, virtual_fill: VirtualFill) -> None:
        """Accumulate the net signed quantity implied by a simulated fill."""
        symbol = virtual_fill.order.contract.tradingsymbol
        signed = virtual_fill.fill.quantity
        if virtual_fill.order.side is Side.SELL:
            signed = -signed
        self._expected[symbol] = self._expected.get(symbol, 0) + signed

    def reconcile(self, portfolio: PaperPortfolio) -> ReconciliationReport:
        actual = {symbol: position.quantity for symbol, position in portfolio.positions.items()}
        drift: dict[str, int] = {}
        for symbol in set(self._expected) | set(actual):
            expected = self._expected.get(symbol, 0)
            portfolio_qty = actual.get(symbol, 0)
            if expected != portfolio_qty:
                drift[symbol] = portfolio_qty - expected
        return ReconciliationReport(reconciled=not drift, drift=drift)

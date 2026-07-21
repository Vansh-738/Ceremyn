from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.domain import PortfolioSnapshot, Position
from ceremyn.strategies.base import StrategyContext
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import NOW, enriched_chain


def test_rejects_naive_now() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StrategyContext(chain=enriched_chain(), now=datetime(2025, 7, 21, 10, 0))


def test_positions_sync_from_portfolio_when_not_given_explicitly() -> None:
    position = Position(contract=make_contract(), quantity=-75, avg_price=Decimal("100"))
    portfolio = PortfolioSnapshot(positions=(position,))
    ctx = StrategyContext(chain=enriched_chain(), now=NOW, portfolio=portfolio)
    assert ctx.positions == (position,)


def test_explicit_positions_are_not_overridden_by_portfolio() -> None:
    explicit = Position(contract=make_contract(strike=25000), quantity=-75, avg_price=Decimal("50"))
    portfolio_position = Position(contract=make_contract(), quantity=75, avg_price=Decimal("100"))
    portfolio = PortfolioSnapshot(positions=(portfolio_position,))
    ctx = StrategyContext(
        chain=enriched_chain(), now=NOW, portfolio=portfolio, positions=(explicit,)
    )
    assert ctx.positions == (explicit,)


def test_other_expiries_defaults_to_empty() -> None:
    ctx = StrategyContext(chain=enriched_chain(), now=NOW)
    assert ctx.other_expiries == {}

"""Domain layer: pure entities and value objects.

This package must not import from any other alphaquant package
(enforced by import-linter).
"""

from alphaquant.domain.chain import ChainEntry, OptionChainSnapshot
from alphaquant.domain.enums import (
    TERMINAL_ORDER_STATUSES,
    Exchange,
    KillSwitchState,
    OptionType,
    OrderStatus,
    OrderType,
    ProductType,
    Side,
    SignalAction,
    TimeFrame,
)
from alphaquant.domain.errors import DomainError, OrderTransitionError
from alphaquant.domain.greeks import Greeks
from alphaquant.domain.instruments import Instrument, OptionContract
from alphaquant.domain.market_data import Candle, Quote
from alphaquant.domain.orders import VALID_TRANSITIONS, Fill, Order
from alphaquant.domain.portfolio import PortfolioExposure, PortfolioGreeks, PortfolioSnapshot
from alphaquant.domain.positions import Position, Trade
from alphaquant.domain.signals import Signal, SignalLeg
from alphaquant.domain.strategy import StrategyDefinition

__all__ = [
    "TERMINAL_ORDER_STATUSES",
    "VALID_TRANSITIONS",
    "Candle",
    "ChainEntry",
    "DomainError",
    "Exchange",
    "Fill",
    "Greeks",
    "Instrument",
    "KillSwitchState",
    "OptionChainSnapshot",
    "OptionContract",
    "OptionType",
    "Order",
    "OrderStatus",
    "OrderTransitionError",
    "OrderType",
    "PortfolioExposure",
    "PortfolioGreeks",
    "PortfolioSnapshot",
    "Position",
    "ProductType",
    "Quote",
    "Side",
    "Signal",
    "SignalAction",
    "SignalLeg",
    "StrategyDefinition",
    "TimeFrame",
    "Trade",
]

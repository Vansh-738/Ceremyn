"""Canned deterministic chains for strategy tests (fixed timestamps, no real clock)."""

from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from alphaquant.core.timeutils import IST
from alphaquant.data.services.chain_analytics import (
    EXPIRY_CUTOFF,
    ChainAnalyticsService,
)
from alphaquant.data.services.pricing import bs_price, time_to_expiry_years
from alphaquant.domain import (
    ChainEntry,
    OptionChainSnapshot,
    OptionType,
    Quote,
    StrategyDefinition,
)
from tests.unit.domain.conftest import make_contract

R = 0.065
SPOT = 24000
EXPIRY = date(2025, 7, 29)
NOW = datetime(2025, 7, 21, 10, 0, tzinfo=IST)  # Monday, DTE 8


def make_definition(strategy_type: str, **params: Any) -> StrategyDefinition:
    return StrategyDefinition(
        id=f"{strategy_type}_test",
        strategy_type=strategy_type,
        name=f"{strategy_type} (test)",
        underlyings=("NIFTY",),
        params=params,
    )


def enriched_chain(
    spot: int = SPOT,
    strikes: Iterable[int] = range(22500, 25600, 100),
    sigma: float = 0.15,
    expiry: date = EXPIRY,
    now: datetime = NOW,
) -> OptionChainSnapshot:
    """Chain whose quotes are exact BS prices at `sigma`, enriched with greeks."""
    t = time_to_expiry_years(
        (datetime.combine(expiry, EXPIRY_CUTOFF, tzinfo=IST) - now).total_seconds()
    )
    entries = []
    for strike in strikes:
        for option_type in (OptionType.CALL, OptionType.PUT):
            contract = make_contract(strike=strike, option_type=option_type, expiry=expiry)
            price = Decimal(
                str(bs_price(spot, float(strike), t, R, sigma, option_type is OptionType.CALL))
            )
            entries.append(
                ChainEntry(
                    contract=contract,
                    quote=Quote(
                        tradingsymbol=contract.tradingsymbol,
                        timestamp=now,
                        last_price=price,
                        bid=price,
                        ask=price,
                        open_interest=100_000,
                    ),
                )
            )
    snapshot = OptionChainSnapshot(
        underlying="NIFTY",
        expiry=expiry,
        spot=Decimal(spot),
        timestamp=now,
        entries=tuple(entries),
    )
    return ChainAnalyticsService(risk_free_rate=R).enrich(snapshot)


def marked_chain(
    marks: dict[tuple[int, OptionType], str],
    spot: int = SPOT,
    expiry: date = EXPIRY,
    now: datetime = NOW,
) -> OptionChainSnapshot:
    """Chain with explicit marks and NO greeks (for exit-path tests)."""
    entries = []
    for (strike, option_type), price_text in marks.items():
        contract = make_contract(strike=strike, option_type=option_type, expiry=expiry)
        price = Decimal(price_text)
        entries.append(
            ChainEntry(
                contract=contract,
                quote=Quote(
                    tradingsymbol=contract.tradingsymbol,
                    timestamp=now,
                    last_price=price,
                    bid=price,
                    ask=price,
                ),
            )
        )
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=expiry,
        spot=Decimal(spot),
        timestamp=now,
        entries=tuple(entries),
    )


def ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)

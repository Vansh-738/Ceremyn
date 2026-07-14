from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from alphaquant.domain import (
    Candle,
    ChainEntry,
    Exchange,
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Quote,
    TimeFrame,
)
from alphaquant.features.context import FeatureContext

AS_OF = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)
EXPIRY = date(2026, 7, 30)


def _contract(strike: int, option_type: OptionType) -> OptionContract:
    return OptionContract(
        tradingsymbol=f"NIFTY26JUL{strike}{option_type.value}",
        exchange=Exchange.NFO,
        underlying="NIFTY",
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=option_type,
        lot_size=75,
    )


def make_chain(
    *,
    spot: str = "24010",
    timestamp: datetime = AS_OF,
    strikes: Sequence[tuple[int, int, int, str]] | None = None,
    spread: str = "1",
    volume: int = 5000,
) -> OptionChainSnapshot:
    """Multi-strike chain. Each strike tuple is (strike, call_oi, put_oi, price)."""
    rows = strikes or [
        (23500, 300_000, 1_200_000, "70"),
        (24000, 500_000, 900_000, "180"),
        (24500, 800_000, 400_000, "90"),
    ]
    entries: list[ChainEntry] = []
    for strike, call_oi, put_oi, price in rows:
        for option_type, oi in ((OptionType.CALL, call_oi), (OptionType.PUT, put_oi)):
            contract = _contract(strike, option_type)
            last = Decimal(price)
            entries.append(
                ChainEntry(
                    contract=contract,
                    quote=Quote(
                        tradingsymbol=contract.tradingsymbol,
                        timestamp=timestamp,
                        last_price=last,
                        bid=last - Decimal(spread),
                        ask=last + Decimal(spread),
                        volume=volume,
                        open_interest=oi,
                    ),
                )
            )
    return OptionChainSnapshot(
        underlying="NIFTY",
        expiry=EXPIRY,
        spot=Decimal(spot),
        timestamp=timestamp,
        entries=tuple(entries),
    )


def make_candles(
    closes: Sequence[float],
    *,
    start: datetime = AS_OF - timedelta(days=60),
    volume: int = 100_000,
) -> tuple[Candle, ...]:
    """Build a daily candle series from a list of closes (band ±1 around each close)."""
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                tradingsymbol="NIFTY 50",
                timeframe=TimeFrame.DAY,
                timestamp=start + timedelta(days=index),
                open=Decimal(str(round(close - 0.2, 2))),
                high=Decimal(str(round(close + 1.0, 2))),
                low=Decimal(str(round(close - 1.0, 2))),
                close=Decimal(str(round(close, 2))),
                volume=volume + index,
            )
        )
    return tuple(candles)


def trending_closes(n: int = 40, start: float = 100.0, step: float = 0.6) -> list[float]:
    return [start + step * i for i in range(n)]


def make_context(
    *,
    chain: OptionChainSnapshot | None = None,
    previous_chain: OptionChainSnapshot | None = None,
    iv_history: Sequence[float] = (),
    closes: Sequence[float] | None = None,
    as_of: datetime = AS_OF,
) -> FeatureContext:
    candles = make_candles(list(closes)) if closes is not None else ()
    return FeatureContext(
        as_of=as_of,
        underlying="NIFTY",
        chain=chain,
        previous_chain=previous_chain,
        iv_history=tuple(iv_history),
        candles=candles,
        risk_free_rate=0.065,
    )


@pytest.fixture
def chain() -> OptionChainSnapshot:
    return make_chain()


@pytest.fixture
def full_context(chain: OptionChainSnapshot) -> FeatureContext:
    """A context with everything populated: chain, IV history, and 40 candles."""
    return make_context(
        chain=chain,
        iv_history=tuple(0.10 + 0.002 * i for i in range(30)),
        closes=trending_closes(40),
    )

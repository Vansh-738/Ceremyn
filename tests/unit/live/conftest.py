from datetime import UTC, datetime

import pytest

from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.domain import OptionContract, OptionType
from ceremyn.live.feed import UnderlyingDefinition
from tests.unit.domain.conftest import make_contract

INDEX_TOKEN = 256265
CALL_TOKEN = 101
PUT_TOKEN = 102
BASE_TS = datetime(2026, 7, 14, 4, 20, tzinfo=UTC)


def nifty_definition() -> UnderlyingDefinition:
    return UnderlyingDefinition(name="NIFTY", index_symbol="NIFTY 50", index_token=INDEX_TOKEN)


def nifty_contracts() -> tuple[OptionContract, OptionContract]:
    expiry = datetime(2026, 7, 28, tzinfo=UTC).date()
    call = make_contract(expiry=expiry).model_copy(update={"broker_token": CALL_TOKEN})
    put = make_contract(expiry=expiry, option_type=OptionType.PUT).model_copy(
        update={"broker_token": PUT_TOKEN}
    )
    return call, put


def tick_payload(
    token: int,
    *,
    last_price: str,
    timestamp: datetime = BASE_TS,
    bid: str | None = None,
    ask: str | None = None,
    volume: int = 1000,
    oi: int = 1000,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "instrument_token": token,
        "last_price": float(last_price),
        "exchange_timestamp": timestamp,
        "volume_traded": volume,
        "oi": oi,
    }
    if bid is not None or ask is not None:
        payload["depth"] = {
            "buy": [] if bid is None else [{"price": float(bid)}],
            "sell": [] if ask is None else [{"price": float(ask)}],
        }
    return payload


@pytest.fixture
def analytics() -> ChainAnalyticsService:
    return ChainAnalyticsService(risk_free_rate=0.065)


@pytest.fixture
def underlyings() -> tuple[UnderlyingDefinition, ...]:
    return (nifty_definition(),)


@pytest.fixture
def contracts() -> tuple[OptionContract, OptionContract]:
    return nifty_contracts()

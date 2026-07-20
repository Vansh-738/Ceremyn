from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from alphaquant.core.exceptions import BrokerError
from alphaquant.core.timeutils import IST
from alphaquant.data.providers.kite import KiteProvider
from alphaquant.domain import AssetClass, OptionType, TimeFrame

NFO_DUMP = [
    {
        "instrument_token": 111,
        "tradingsymbol": "NIFTY25JUL24500CE",
        "name": "NIFTY",
        "expiry": date(2025, 7, 15),
        "strike": 24500.0,
        "tick_size": 0.05,
        "lot_size": 75,
        "instrument_type": "CE",
        "segment": "NFO-OPT",
        "exchange": "NFO",
    },
    {
        "instrument_token": 112,
        "tradingsymbol": "BANKNIFTY25JUL56000PE",
        "name": "BANKNIFTY",
        "expiry": datetime(2025, 7, 29, 0, 0),  # kite sometimes returns datetimes
        "strike": 56000.0,
        "tick_size": 0.05,
        "lot_size": 30,
        "instrument_type": "PE",
        "segment": "NFO-OPT",
        "exchange": "NFO",
    },
    {  # excluded from options: future, not an option (included by fetch_future_contracts)
        "instrument_token": 113,
        "tradingsymbol": "NIFTY25JULFUT",
        "name": "NIFTY",
        "expiry": date(2025, 7, 31),
        "strike": 0.0,
        "tick_size": 0.05,
        "lot_size": 75,
        "instrument_type": "FUT",
        "segment": "NFO-FUT",
        "exchange": "NFO",
    },
    {  # excluded: unwanted underlying
        "instrument_token": 114,
        "tradingsymbol": "FINNIFTY25JUL23500CE",
        "name": "FINNIFTY",
        "expiry": date(2025, 7, 29),
        "strike": 23500.0,
        "tick_size": 0.05,
        "lot_size": 65,
        "instrument_type": "CE",
        "segment": "NFO-OPT",
        "exchange": "NFO",
    },
]

NSE_DUMP = [
    {
        "instrument_token": 738561,
        "tradingsymbol": "RELIANCE",
        "name": "RELIANCE INDUSTRIES",
        "isin": "INE002A01018",
        "tick_size": 0.05,
        "lot_size": 1,
        "instrument_type": "EQ",
        "segment": "NSE",
        "exchange": "NSE",
    },
    {
        "instrument_token": 999999,
        "tradingsymbol": "NIFTYBEES",
        "name": "NIPPON INDIA ETF NIFTY BEES",
        "isin": "INF204KB17I5",
        "tick_size": 0.01,
        "lot_size": 1,
        "instrument_type": "EQ",
        "segment": "NSE",
        "exchange": "NSE",
    },
    {  # excluded: unwanted tradingsymbol
        "instrument_token": 111111,
        "tradingsymbol": "INFY",
        "name": "INFOSYS",
        "isin": "INE009A01021",
        "tick_size": 0.05,
        "lot_size": 1,
        "instrument_type": "EQ",
        "segment": "NSE",
        "exchange": "NSE",
    },
]

QUOTE_PAYLOAD = {
    "last_price": 180.5,
    "volume": 8956234,
    "oi": 4521300,
    "timestamp": datetime(2025, 7, 11, 15, 29, 58),  # naive IST from kite
    "depth": {
        "buy": [{"price": 180.4, "quantity": 750}],
        "sell": [{"price": 180.6, "quantity": 300}],
    },
}


class FakeKite:
    def __init__(self) -> None:
        self.quote_calls: list[list[str]] = []
        self.access_token: str | None = None

    def instruments(self, exchange: str) -> list[dict[str, Any]]:
        if exchange == "NFO":
            return NFO_DUMP
        if exchange == "NSE":
            return NSE_DUMP
        raise AssertionError(f"unexpected exchange {exchange!r}")

    def quote(self, symbols: list[str]) -> dict[str, Any]:
        self.quote_calls.append(symbols)
        return {symbol: QUOTE_PAYLOAD for symbol in symbols}

    def ltp(self, symbols: list[str]) -> dict[str, Any]:
        return {symbol: {"last_price": 24502.15} for symbol in symbols}

    def historical_data(
        self, token: int, start: object, end: object, interval: str, oi: bool = False
    ) -> list[dict[str, Any]]:
        assert interval == "day"
        return [
            {
                "date": datetime(2025, 7, 11, 0, 0),
                "open": 24510.0,
                "high": 24620.5,
                "low": 24450.0,
                "close": 24580.25,
                "volume": 15478236,
                "oi": 12456300,
            }
        ]

    def generate_session(self, request_token: str, api_secret: str) -> dict[str, str]:
        if request_token != "good-token":
            raise Exception("Token is invalid or has expired")
        return {"access_token": "access-123"}

    def set_access_token(self, token: str) -> None:
        self.access_token = token


@pytest.fixture
def fake() -> FakeKite:
    return FakeKite()


@pytest.fixture
def provider(fake: FakeKite) -> KiteProvider:
    return KiteProvider(fake)


class TestInstruments:
    async def test_filters_index_options(self, provider: KiteProvider) -> None:
        contracts = await provider.fetch_option_contracts(("NIFTY", "BANKNIFTY"))
        assert [c.tradingsymbol for c in contracts] == [
            "NIFTY25JUL24500CE",
            "BANKNIFTY25JUL56000PE",
        ]

    async def test_contract_mapping(self, provider: KiteProvider) -> None:
        contracts = await provider.fetch_option_contracts(("BANKNIFTY",))
        (contract,) = contracts
        assert contract.strike == Decimal(56000)
        assert contract.option_type is OptionType.PUT
        assert contract.lot_size == 30
        assert contract.broker_token == 112
        assert contract.expiry == date(2025, 7, 29)  # datetime normalized to date


class TestFutureContracts:
    async def test_filters_futures_for_wanted_underlyings(self, provider: KiteProvider) -> None:
        contracts = await provider.fetch_future_contracts(("NIFTY", "BANKNIFTY"))
        assert [c.tradingsymbol for c in contracts] == ["NIFTY25JULFUT"]

    async def test_contract_mapping(self, provider: KiteProvider) -> None:
        (contract,) = await provider.fetch_future_contracts(("NIFTY",))
        assert contract.asset_class is AssetClass.FUTURES
        assert contract.underlying == "NIFTY"
        assert contract.expiry == date(2025, 7, 31)
        assert contract.lot_size == 75
        assert contract.broker_token == 113


class TestCashInstruments:
    async def test_fetches_equity_instruments(self, provider: KiteProvider) -> None:
        (equity,) = await provider.fetch_equity_instruments(("RELIANCE",))
        assert equity.asset_class is AssetClass.EQUITY
        assert equity.tradingsymbol == "RELIANCE"
        assert equity.underlying == "RELIANCE"
        assert equity.isin == "INE002A01018"
        assert equity.broker_token == 738561
        assert equity.lot_size == 1

    async def test_fetches_etf_instruments(self, provider: KiteProvider) -> None:
        (etf,) = await provider.fetch_etf_instruments(("NIFTYBEES",))
        assert etf.asset_class is AssetClass.ETF
        assert etf.tradingsymbol == "NIFTYBEES"
        assert etf.isin == "INF204KB17I5"
        assert etf.broker_token == 999999

    async def test_unwanted_tradingsymbol_excluded(self, provider: KiteProvider) -> None:
        assert await provider.fetch_equity_instruments(("RELIANCE",)) != []
        assert await provider.fetch_equity_instruments(("DOES_NOT_EXIST",)) == []


class TestQuotes:
    async def test_quote_mapping(self, provider: KiteProvider) -> None:
        quotes = await provider.quotes(["NFO:NIFTY25JUL24500CE"])
        quote = quotes["NFO:NIFTY25JUL24500CE"]
        assert quote.tradingsymbol == "NIFTY25JUL24500CE"
        assert quote.last_price == Decimal("180.5")
        assert quote.bid == Decimal("180.4")
        assert quote.ask == Decimal("180.6")
        assert quote.open_interest == 4521300
        assert quote.timestamp.tzinfo is IST  # naive kite timestamp made explicit

    async def test_batching(self, fake: FakeKite, provider: KiteProvider) -> None:
        symbols = [f"NFO:SYM{i}" for i in range(900)]
        await provider.quotes(symbols)
        assert [len(batch) for batch in fake.quote_calls] == [400, 400, 100]

    async def test_spot_price(self, provider: KiteProvider) -> None:
        assert await provider.spot_price("NIFTY") == Decimal("24502.15")

    async def test_unmapped_underlying_raises(self, provider: KiteProvider) -> None:
        with pytest.raises(BrokerError, match="SENSEX"):
            await provider.spot_price("SENSEX")


class TestHistory:
    async def test_candle_mapping(self, provider: KiteProvider) -> None:
        candles = await provider.historical_candles(
            111,
            "NIFTY25JUL24500CE",
            TimeFrame.DAY,
            datetime(2025, 7, 1, tzinfo=IST),
            datetime(2025, 7, 11, tzinfo=IST),
        )
        (candle,) = candles
        assert candle.close == Decimal("24580.25")
        assert candle.open_interest == 12456300
        assert candle.timestamp.tzinfo is IST


class TestAuth:
    async def test_authenticate_sets_access_token(
        self, fake: FakeKite, provider: KiteProvider
    ) -> None:
        await provider.authenticate("good-token", api_secret="secret")
        assert fake.access_token == "access-123"

    async def test_bad_request_token_raises_broker_error(self, provider: KiteProvider) -> None:
        with pytest.raises(BrokerError, match="session exchange failed"):
            await provider.authenticate("bad-token", api_secret="secret")

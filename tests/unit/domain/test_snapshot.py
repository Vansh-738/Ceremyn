from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ceremyn.domain import MarketSnapshot, OptionChainSnapshot, OptionType, TimeFrame
from ceremyn.domain.market_data import Candle
from tests.unit.domain.conftest import make_contract, make_quote

TS = datetime(2025, 7, 14, 10, 0, tzinfo=UTC)


def make_candle(**overrides: object) -> Candle:
    defaults: dict[str, object] = {
        "tradingsymbol": "RELIANCE",
        "timeframe": TimeFrame.DAY,
        "timestamp": TS,
        "open": Decimal(2900),
        "high": Decimal(2950),
        "low": Decimal(2880),
        "close": Decimal(2920),
    }
    defaults.update(overrides)
    return Candle.model_validate(defaults)


def make_chain(underlying: str = "NIFTY") -> OptionChainSnapshot:
    contract = make_contract(underlying=underlying, option_type=OptionType.CALL)
    from ceremyn.domain import ChainEntry

    return OptionChainSnapshot(
        underlying=underlying,
        expiry=date(2025, 7, 29),
        spot=Decimal(24010),
        timestamp=TS,
        entries=(
            ChainEntry(
                contract=contract,
                quote=make_quote(tradingsymbol=contract.tradingsymbol),
            ),
        ),
    )


class TestComposition:
    def test_quote_only(self) -> None:
        snapshot = MarketSnapshot(underlying="RELIANCE", timestamp=TS, quote=make_quote())
        assert snapshot.quote is not None
        assert snapshot.candle is None
        assert snapshot.option_chain is None

    def test_candle_only(self) -> None:
        snapshot = MarketSnapshot(underlying="RELIANCE", timestamp=TS, candle=make_candle())
        assert snapshot.candle is not None
        assert snapshot.quote is None
        assert snapshot.option_chain is None

    def test_option_chain_only(self) -> None:
        chain = make_chain()
        snapshot = MarketSnapshot(underlying="NIFTY", timestamp=TS, option_chain=chain)
        assert snapshot.option_chain is chain
        assert snapshot.quote is None
        assert snapshot.candle is None

    def test_quote_and_option_chain_together(self) -> None:
        chain = make_chain()
        snapshot = MarketSnapshot(
            underlying="NIFTY",
            timestamp=TS,
            quote=make_quote(tradingsymbol="NIFTY 50"),
            option_chain=chain,
        )
        assert snapshot.quote is not None
        assert snapshot.option_chain is chain

    def test_all_three_together(self) -> None:
        chain = make_chain()
        snapshot = MarketSnapshot(
            underlying="NIFTY",
            timestamp=TS,
            quote=make_quote(tradingsymbol="NIFTY 50"),
            candle=make_candle(tradingsymbol="NIFTY 50"),
            option_chain=chain,
        )
        assert snapshot.quote is not None
        assert snapshot.candle is not None
        assert snapshot.option_chain is chain


class TestValidation:
    def test_empty_snapshot_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one of"):
            MarketSnapshot(underlying="RELIANCE", timestamp=TS)

    def test_option_chain_underlying_mismatch_rejected(self) -> None:
        chain = make_chain(underlying="NIFTY")
        with pytest.raises(ValidationError, match="option_chain.underlying must match"):
            MarketSnapshot(underlying="BANKNIFTY", timestamp=TS, option_chain=chain)

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            MarketSnapshot(
                underlying="RELIANCE",
                timestamp=datetime(2025, 7, 14, 10, 0),  # naive
                quote=make_quote(),
            )

    def test_empty_underlying_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MarketSnapshot(underlying="", timestamp=TS, quote=make_quote())

    def test_frozen(self) -> None:
        snapshot = MarketSnapshot(underlying="RELIANCE", timestamp=TS, quote=make_quote())
        with pytest.raises(ValidationError):
            snapshot.underlying = "OTHER"  # type: ignore[misc]


class TestAssetClassNeutrality:
    """The whole point of MarketSnapshot: it must not require an option chain."""

    def test_equity_snapshot_has_no_option_chain(self) -> None:
        snapshot = MarketSnapshot(underlying="RELIANCE", timestamp=TS, candle=make_candle())
        assert snapshot.option_chain is None

    def test_option_underlying_snapshot_composes_existing_chain_unchanged(self) -> None:
        """OptionChainSnapshot itself is untouched -- MarketSnapshot only wraps it."""
        chain = make_chain()
        snapshot = MarketSnapshot(underlying="NIFTY", timestamp=TS, option_chain=chain)
        assert snapshot.option_chain.atm_strike == chain.atm_strike
        assert snapshot.option_chain.pcr == chain.pcr
